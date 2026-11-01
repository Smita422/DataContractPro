"""Deterministic data transformation and lineage enrichment engine."""

from datetime import datetime, timezone
from typing import Optional
import numpy as np
import pandas as pd

from schemaguard.utils.logger import logger


class DataTransformer:
    """Transforms validated records, derives calculated columns, and attaches source lineage."""

    @classmethod
    def transform(
        cls,
        dataset_name: str,
        valid_df: pd.DataFrame,
        batch_id: str,
        run_id: str,
        source_file: str,
    ) -> pd.DataFrame:
        """Route to dataset-specific transformation without mutating the original raw input."""
        if valid_df.empty:
            return valid_df.copy()

        if dataset_name == "customers":
            return cls._transform_customers(valid_df, batch_id, run_id, source_file)
        elif dataset_name == "orders":
            return cls._transform_orders(valid_df, batch_id, run_id, source_file)
        else:
            df = valid_df.copy()
            cls._attach_lineage(df, batch_id, run_id, source_file)
            return df

    @classmethod
    def _transform_customers(
        cls,
        valid_df: pd.DataFrame,
        batch_id: str,
        run_id: str,
        source_file: str,
    ) -> pd.DataFrame:
        """Apply customer-specific normalization and lineage attachment."""
        df = valid_df.copy()

        df["customer_id"] = df["customer_id"].astype(str).str.strip()
        df["customer_name"] = df["customer_name"].astype(str).str.strip()
        df["email"] = df["email"].astype(str).str.strip().str.lower()
        if "city" in df.columns:
            df["city"] = df["city"].apply(lambda v: str(v).strip() if v and str(v).strip() != "" else None)
        df["customer_status"] = df["customer_status"].astype(str).str.strip().str.lower()

        # Normalize timestamp to UTC
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)

        cls._attach_lineage(df, batch_id, run_id, source_file)

        # Select only published schema columns
        target_cols = [
            "customer_id",
            "customer_name",
            "email",
            "city",
            "customer_status",
            "created_at",
            "_sg_batch_id",
            "_sg_run_id",
            "_sg_source_file",
            "_sg_loaded_at",
        ]
        return df[[c for c in target_cols if c in df.columns]]

    @classmethod
    def _transform_orders(
        cls,
        valid_df: pd.DataFrame,
        batch_id: str,
        run_id: str,
        source_file: str,
    ) -> pd.DataFrame:
        """Apply orders-specific calculation (total_amount), normalization, and lineage."""
        df = valid_df.copy()

        df["order_id"] = df["order_id"].astype(str).str.strip()
        df["customer_id"] = df["customer_id"].astype(str).str.strip()
        df["product_name"] = df["product_name"].astype(str).str.strip()

        # Coerce numeric fields and derive total_amount = quantity * unit_price
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype(int)
        df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").astype(float)
        df["total_amount"] = (df["quantity"] * df["unit_price"]).round(2)

        df["order_status"] = df["order_status"].astype(str).str.strip().str.lower()
        df["payment_method"] = df["payment_method"].astype(str).str.strip().str.lower()

        if "delivery_status" in df.columns:
            df["delivery_status"] = df["delivery_status"].apply(
                lambda v: str(v).strip().lower() if v and str(v).strip() != "" else None
            )

        # Normalize timestamps to UTC
        df["order_date"] = pd.to_datetime(df["order_date"], utc=True)
        df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)

        cls._attach_lineage(df, batch_id, run_id, source_file)

        target_cols = [
            "order_id",
            "customer_id",
            "order_date",
            "product_name",
            "quantity",
            "unit_price",
            "total_amount",
            "order_status",
            "payment_method",
            "updated_at",
            "delivery_status",
            "_sg_batch_id",
            "_sg_run_id",
            "_sg_source_file",
            "_sg_loaded_at",
        ]
        return df[[c for c in target_cols if c in df.columns]]

    @staticmethod
    def _attach_lineage(
        df: pd.DataFrame, batch_id: str, run_id: str, source_file: str
    ) -> None:
        """Attach lineage tracking columns to dataframe."""
        df["_sg_batch_id"] = batch_id
        df["_sg_run_id"] = run_id
        df["_sg_source_file"] = source_file
        df["_sg_loaded_at"] = pd.Timestamp.now(tz=timezone.utc)
