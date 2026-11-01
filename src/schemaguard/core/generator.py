"""Configurable Synthetic Data Generator for SchemaGuard.

Generates realistic, contract-compliant customer and order datasets with
deterministic random seeding and configurable negative data injection for
chaos, edge-case, and data quality testing.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
from typing import Any, Dict, List, Literal, Optional, Tuple
import numpy as np
import pandas as pd

from schemaguard.utils.logger import logger

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
]

DOMAINS = ["example.com", "mail.test", "corp.local", "inbox.org", "sample.net"]

CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Seattle",
    "Denver", "Boston", "San Francisco", "Miami", "Atlanta", "Portland",
]

PRODUCTS = [
    ("Wireless Mouse", 29.99),
    ("Mechanical Keyboard", 119.50),
    ("USB-C Hub Multiport", 45.00),
    ("27-inch 4K Monitor", 349.99),
    ("Ergonomic Desk Chair", 289.00),
    ("Noise Cancelling Headphones", 199.95),
    ("Aluminum Laptop Stand", 39.99),
    ("1080p HD Webcam", 69.50),
    ("Ultra-fast NVMe SSD 1TB", 109.00),
    ("Braided USB-C Cable 2m", 15.99),
]

CUSTOMER_STATUSES = ["active", "inactive"]
ORDER_STATUSES = ["pending", "shipped", "delivered", "cancelled"]
PAYMENT_METHODS = ["card", "upi", "cash", "netbanking"]
DELIVERY_STATUSES = ["pending", "dispatched", "in_transit", "delivered", "failed"]


class SyntheticDataGenerator:
    """Deterministic synthetic data generator respecting SchemaGuard contracts."""

    def __init__(self, seed: Optional[int] = 42):
        self.seed = seed
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)

    def reset_seed(self, seed: Optional[int] = None) -> None:
        """Reset the random number generator seed."""
        self.seed = seed if seed is not None else self.seed
        self._rng = random.Random(self.seed)
        self._np_rng = np.random.default_rng(self.seed)

    def generate_customers(
        self,
        count: int,
        output_file: Optional[Path | str] = None,
        corruption_rate: float = 0.0,
        corruption_options: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """Generate synthetic customer records adhering to the customers contract.

        Parameters:
            count: Number of customer records to generate.
            output_file: Optional path to save CSV output.
            corruption_rate: Baseline rate of invalid records (0.0 to 1.0).
            corruption_options: Fine-grained corruption percentages:
                - 'null_required_pct'
                - 'invalid_enum_pct'
                - 'duplicate_pk_pct'
                - 'duplicate_email_pct'
                - 'invalid_timestamp_pct'
        """
        if count < 0:
            raise ValueError(f"count must be non-negative, got {count}")

        if count == 0:
            df = pd.DataFrame(columns=[
                "customer_id", "customer_name", "email", "city", "customer_status", "created_at"
            ])
            if output_file:
                Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(output_file, index=False)
            return df

        base_time = datetime(2026, 1, 1, 8, 0, 0)
        records: List[Dict[str, Any]] = []

        # Generate base clean records
        for i in range(1, count + 1):
            first = self._rng.choice(FIRST_NAMES)
            last = self._rng.choice(LAST_NAMES)
            name = f"{first} {last}"
            domain = self._rng.choice(DOMAINS)
            email = f"{first.lower()}.{last.lower()}.{i}@{domain}"
            city = self._rng.choice(CITIES) if self._rng.random() > 0.15 else None
            status = self._rng.choices(CUSTOMER_STATUSES, weights=[0.85, 0.15])[0]
            created_at = (base_time + timedelta(minutes=i * 7)).strftime("%Y-%m-%d %H:%M:%S")

            records.append({
                "customer_id": f"CUST-{i:07d}",
                "customer_name": name,
                "email": email,
                "city": city or "",
                "customer_status": status,
                "created_at": created_at,
            })

        df = pd.DataFrame(records)

        # Apply controlled negative injections if requested
        if corruption_rate > 0.0 or corruption_options:
            df = self._corrupt_customers(df, corruption_rate, corruption_options or {})

        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
            logger.info(f"Generated {len(df)} customer records to {path}")

        return df

    def generate_orders(
        self,
        count: int,
        customer_ids: Optional[List[str]] = None,
        customers_file: Optional[Path | str] = None,
        output_file: Optional[Path | str] = None,
        include_delivery_status: bool = False,
        corruption_rate: float = 0.0,
        corruption_options: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """Generate synthetic order records referencing valid customer IDs.

        Parameters:
            count: Number of order records to generate.
            customer_ids: Explicit list of valid customer_id strings to reference.
            customers_file: CSV file from which to read valid customer IDs.
            output_file: Optional path to save CSV output.
            include_delivery_status: Whether to include optional delivery_status (v1.1.0).
            corruption_rate: Baseline rate of invalid records (0.0 to 1.0).
            corruption_options: Fine-grained corruption percentages:
                - 'null_required_pct'
                - 'invalid_fk_pct'
                - 'negative_qty_pct'
                - 'negative_price_pct'
                - 'invalid_enum_pct'
                - 'duplicate_pk_pct'
                - 'invalid_timestamp_pct'
        """
        if count < 0:
            raise ValueError(f"count must be non-negative, got {count}")

        cols = [
            "order_id", "customer_id", "order_date", "product_name",
            "quantity", "unit_price", "order_status", "payment_method", "updated_at"
        ]
        if include_delivery_status:
            cols.append("delivery_status")

        if count == 0:
            df = pd.DataFrame(columns=cols)
            if output_file:
                Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(output_file, index=False)
            return df

        # Resolve available customer references
        available_cust_ids = list(customer_ids) if customer_ids else []
        if not available_cust_ids and customers_file:
            cust_df = pd.read_csv(customers_file)
            if "customer_id" in cust_df.columns:
                available_cust_ids = cust_df["customer_id"].dropna().tolist()

        if not available_cust_ids:
            # Fallback customer IDs for standalone generation
            available_cust_ids = [f"CUST-{i:07d}" for i in range(1, max(10, count // 3) + 1)]

        base_time = datetime(2026, 2, 1, 9, 0, 0)
        records: List[Dict[str, Any]] = []

        for i in range(1, count + 1):
            cust_id = self._rng.choice(available_cust_ids)
            order_date_dt = base_time + timedelta(minutes=i * 3)
            order_date = order_date_dt.strftime("%Y-%m-%d %H:%M:%S")
            updated_at = (order_date_dt + timedelta(minutes=self._rng.randint(2, 60))).strftime("%Y-%m-%d %H:%M:%S")

            product, default_price = self._rng.choice(PRODUCTS)
            quantity = int(self._np_rng.integers(1, 6))
            # Slight price variation
            price_factor = round(self._rng.uniform(0.95, 1.05), 2)
            unit_price = round(default_price * price_factor, 2)

            order_status = self._rng.choices(
                ORDER_STATUSES, weights=[0.25, 0.20, 0.50, 0.05]
            )[0]
            payment_method = self._rng.choices(
                PAYMENT_METHODS, weights=[0.40, 0.35, 0.15, 0.10]
            )[0]

            rec = {
                "order_id": f"ORD-{i:08d}",
                "customer_id": cust_id,
                "order_date": order_date,
                "product_name": product,
                "quantity": quantity,
                "unit_price": unit_price,
                "order_status": order_status,
                "payment_method": payment_method,
                "updated_at": updated_at,
            }
            if include_delivery_status:
                rec["delivery_status"] = self._rng.choice(DELIVERY_STATUSES)

            records.append(rec)

        df = pd.DataFrame(records)

        # Apply controlled negative injections if requested
        if corruption_rate > 0.0 or corruption_options:
            df = self._corrupt_orders(df, corruption_rate, corruption_options or {})

        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
            logger.info(f"Generated {len(df)} order records to {path}")

        return df

    # ==========================================================================
    # Controlled Negative Data Injection Methods
    # ==========================================================================

    def _corrupt_customers(
        self,
        df: pd.DataFrame,
        baseline_rate: float,
        options: Dict[str, float],
    ) -> pd.DataFrame:
        """Inject controlled synthetic anomalies into customer DataFrame."""
        n = len(df)
        if n == 0:
            return df

        df = df.copy()

        # 1. Null required field (customer_name)
        pct = options.get("null_required_pct", baseline_rate * 0.25)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "customer_name"] = ""

        # 2. Invalid enum (customer_status)
        pct = options.get("invalid_enum_pct", baseline_rate * 0.25)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "customer_status"] = "BANNED_STATUS"

        # 3. Duplicate emails
        pct = options.get("duplicate_email_pct", baseline_rate * 0.20)
        k = max(1 if pct > 0 and n > 1 else 0, int(n * pct))
        if k > 0 and n >= 2:
            donor_email = df.loc[0, "email"]
            idx = self._rng.sample(range(1, n), min(k, n - 1))
            df.loc[idx, "email"] = donor_email

        # 4. Duplicate primary key
        pct = options.get("duplicate_pk_pct", baseline_rate * 0.15)
        k = max(1 if pct > 0 and n > 1 else 0, int(n * pct))
        if k > 0 and n >= 2:
            donor_id = df.loc[0, "customer_id"]
            idx = self._rng.sample(range(1, n), min(k, n - 1))
            df.loc[idx, "customer_id"] = donor_id

        # 5. Invalid timestamp
        pct = options.get("invalid_timestamp_pct", baseline_rate * 0.15)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "created_at"] = "NOT-A-TIMESTAMP"

        return df

    def _corrupt_orders(
        self,
        df: pd.DataFrame,
        baseline_rate: float,
        options: Dict[str, float],
    ) -> pd.DataFrame:
        """Inject controlled synthetic anomalies into orders DataFrame."""
        n = len(df)
        if n == 0:
            return df

        df = df.copy()

        # 1. Invalid foreign keys
        pct = options.get("invalid_fk_pct", baseline_rate * 0.30)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "customer_id"] = "CUST-NONEXISTENT-99999"

        # 2. Negative quantity
        pct = options.get("negative_qty_pct", baseline_rate * 0.25)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "quantity"] = -2

        # 3. Negative unit price
        pct = options.get("negative_price_pct", baseline_rate * 0.20)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "unit_price"] = -49.99

        # 4. Invalid enum values (order_status / payment_method)
        pct = options.get("invalid_enum_pct", baseline_rate * 0.25)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "order_status"] = "INVALID_STATUS"
            df.loc[idx, "payment_method"] = "BITCOIN"

        # 5. Duplicate primary key
        pct = options.get("duplicate_pk_pct", baseline_rate * 0.15)
        k = max(1 if pct > 0 and n > 1 else 0, int(n * pct))
        if k > 0 and n >= 2:
            donor_id = df.loc[0, "order_id"]
            idx = self._rng.sample(range(1, n), min(k, n - 1))
            df.loc[idx, "order_id"] = donor_id

        # 6. Malformed timestamps
        pct = options.get("invalid_timestamp_pct", baseline_rate * 0.15)
        k = max(1 if pct > 0 and n > 0 else 0, int(n * pct))
        if k > 0:
            idx = self._rng.sample(range(n), min(k, n))
            df.loc[idx, "order_date"] = "INVALID-DATE-FORMAT"

        return df
