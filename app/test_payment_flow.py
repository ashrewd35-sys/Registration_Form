"""Isolated API tests for payment gating, backed by a temporary SQLite database."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./payment_flow_tests.db")

import server  # noqa: E402
from lib.db import Base, get_session  # noqa: E402


class PaymentFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(cls.temp_dir.name) / "payment-flow.sqlite3"
        cls.test_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        cls.test_sessions = async_sessionmaker(cls.test_engine, expire_on_commit=False)

        async def create_tables():
            async with cls.test_engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        asyncio.run(create_tables())

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cls.test_engine.dispose())
        cls.temp_dir.cleanup()

    async def _test_session(self):
        async with self.test_sessions() as session:
            yield session

    def test_manual_review_is_required_before_application_submission(self):
        environment = {
            "ADMIN_PIN": "test-only-admin-pin-long-enough",
            "UPI_VPA": "information.tatasolar-1@okicici",
            "UPI_PAYEE_NAME": "Test Payee",
            "UPI_PAYMENT_NOTE": "Application fee",
            "APPLICATION_FEE_INR": "299",
        }
        with (
            patch.dict(os.environ, environment),
            patch("server.init_db"),
            patch("server.close_db"),
        ):
            server.app.dependency_overrides[get_session] = self._test_session
            try:
                with TestClient(server.app) as client:
                    self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
                    self.assertEqual(client.get("/").status_code, 200)
                    self.assertEqual(client.get("/admin").status_code, 200)

                    application = {
                        "full_name": "Test Applicant",
                        "phone": "7000000001",
                        "whatsapp": "7000000001",
                        "email": "applicant@example.com",
                        "district": "Kolkata",
                        "professions": ["Solar/Renewable Energy Sector"],
                        "has_shop": "Operating Individually",
                        "experience": "0-2",
                        "comments": "",
                    }
                    created = client.post("/api/payments/initiate", json={"application": application})
                    self.assertEqual(created.status_code, 201, created.text)
                    payment = created.json()
                    payment_id = payment["id"]
                    self.assertEqual(payment["status"], "pending")
                    self.assertEqual(payment["amount"], 299)
                    self.assertEqual(payment["upi_vpa"], environment["UPI_VPA"])
                    self.assertIn("upi://pay?", payment["upi_link"])

                    qr = client.get(f"/api/payments/{payment_id}/qr.svg")
                    self.assertEqual(qr.status_code, 200)
                    self.assertIn("svg", qr.headers["content-type"])

                    body = {"payment_id": payment_id}
                    self.assertEqual(client.post("/api/applications", json=body).status_code, 402)
                    self.assertEqual(
                        client.post(f"/api/payments/{payment_id}/verify", json={"utr": "123"}).status_code,
                        422,
                    )
                    utr = "423456789012"
                    review = client.post(f"/api/payments/{payment_id}/verify", json={"utr": utr})
                    self.assertEqual(review.status_code, 200, review.text)
                    self.assertEqual(review.json()["status"], "pending_review")
                    self.assertEqual(client.post("/api/applications", json=body).status_code, 402)
                    self.assertEqual(client.get("/api/admin/payments").status_code, 401)

                    login = client.post("/api/admin/login", json={"pin": environment["ADMIN_PIN"]})
                    self.assertEqual(login.status_code, 200, login.text)
                    auth = {"Authorization": f"Bearer {login.json()['token']}"}
                    self.assertEqual(
                        client.post(f"/api/admin/payments/{payment_id}/confirm", headers=auth).status_code,
                        200,
                    )
                    submitted = client.post("/api/applications", json=body)
                    self.assertEqual(submitted.status_code, 201, submitted.text)
                    reference = submitted.json()["reference_no"]
                    self.assertRegex(reference, r"^TPS-\d{4}-[A-Z0-9]{5}$")
                    duplicate_submit = client.post("/api/applications", json=body)
                    self.assertEqual(duplicate_submit.json()["reference_no"], reference)

                    admin_payments = client.get("/api/admin/payments", headers=auth)
                    self.assertEqual(admin_payments.status_code, 200)
                    self.assertEqual(admin_payments.json()[0]["utr"], utr)
                    self.assertEqual(admin_payments.json()[0]["applicant_name"], "Test Applicant")
                    admin_applications = client.get("/api/admin/applications", headers=auth)
                    self.assertEqual(admin_applications.status_code, 200)
                    self.assertEqual(admin_applications.json()[0]["reference_no"], reference)

                    second_payment = client.post(
                        "/api/payments/initiate",
                        json={"application": application},
                    ).json()
                    duplicate_utr = client.post(
                        f"/api/payments/{second_payment['id']}/verify",
                        json={"utr": utr},
                    )
                    self.assertEqual(duplicate_utr.status_code, 409)

                    failed = client.post(
                        "/api/payments/initiate",
                        json={"application": application},
                    ).json()
                    self.assertEqual(
                        client.post(f"/api/payments/{failed['id']}/fail").json()["status"],
                        "failed",
                    )
                    retry = client.post(f"/api/payments/{failed['id']}/retry")
                    self.assertEqual(retry.status_code, 201, retry.text)
                    self.assertEqual(retry.json()["status"], "pending")
            finally:
                server.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
