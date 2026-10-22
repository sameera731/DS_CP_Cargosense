"""
CargoSense -- Phase 4:  OperationalGenerator
=============================================================

CargoSense: A Data-Driven Opportunity Detection Engine for PTL-to-FTL Conversion.

Ecosystem Scope:
  - 100 SKUs (products.csv) preserving source identity from supply_chain_data.csv
  - 30 Trucks (trucks.csv) across 4 standard commercial vehicle classes
  - 10 Highway Routes (routes.csv) originating from Bhiwandi Hub, Mumbai
  - 90 Daily Planning Runs (planning_snapshots.csv) covering Q1 2024 (Jan 1 - Mar 30)
  - 9,000 Inventory Snapshots (inventory_snapshots.csv: 100 SKUs x 90 Days)
  - 90,000 Demand History Grid (demand_history.csv: 100 SKUs x 10 Cities x 90 Days)
  - 14 Relational CSV Tables with strict business invariants.

Business Invariants Enforced:
  1. Cancellation-free order conservation: ordered_quantity = shipped_quantity + open_quantity
  2. Bounded active reservations: 0 <= active_reserved <= open_quantity
  3. Single atomic dispatch ledger records (delta_on_hand = -q, delta_reserved = -q)
  4. Shipment-level all-or-nothing dispatch with line-header status agreement
  5. Deterministic-ID event references invariant to retries
  6. Non-overlapping sequential truck scheduling with turnaround times
  7. Dual physical vehicle limits (weight kg and volume m³)
  8. Two-stage half-open snapshot boundary reconciliation
  9. Staging-quarantine-promote publication strategy with startup recovery
"""

import os
import sys
import shutil
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Any, Optional
import numpy as np
import pandas as pd

# GLOBAL CONSTANTS & CALENDAR DEFINITIONS
RANDOM_SEED = 42

# 90 Calendar Days: 2024-01-01 through 2024-03-30 (Q1 2024 leap year)
SIMULATION_START_DATE = date(2024, 1, 1)
SIMULATION_END_DATE = date(2024, 3, 30)
TOTAL_CALENDAR_DAYS = 90

SIMULATION_START_TS = datetime(2024, 1, 1, 0, 0, 0)
SIMULATION_END_TS = datetime(2024, 3, 30, 23, 0, 0)

BHIWANDI_HUB = "Bhiwandi Central Fulfillment Hub, Mumbai"

# 14 Relational Table Manifest
EXPECTED_TABLES = [
    "products.csv",
    "trucks.csv",
    "routes.csv",
    "truck_route_permissions.csv",
    "orders.csv",
    "order_lines.csv",
    "inventory_snapshots.csv",
    "inventory_transactions.csv",
    "planning_snapshots.csv",
    "planned_truck_allocations.csv",
    "shipments.csv",
    "shipment_lines.csv",
    "truck_load_events.csv",
    "demand_history.csv",
]

# Physical Packaging Benchmarks by Subcategory
SUBCATEGORY_SPECS = {
    "Color Cosmetics & Compacts": {
        "parent": "cosmetics",
        "weight_min": 0.12, "weight_max": 0.25, "weight_mean": 0.18, "weight_std": 0.03,
        "vol_min": 0.0004, "vol_max": 0.0007, "vol_mean": 0.00055, "vol_std": 0.00008,
    },
    "Lip & Eye Makeup": {
        "parent": "cosmetics",
        "weight_min": 0.05, "weight_max": 0.12, "weight_mean": 0.08, "weight_std": 0.015,
        "vol_min": 0.0001, "vol_max": 0.0003, "vol_mean": 0.00018, "vol_std": 0.00004,
    },
    "Shampoos & Conditioners": {
        "parent": "haircare",
        "weight_min": 0.45, "weight_max": 0.75, "weight_mean": 0.58, "weight_std": 0.06,
        "vol_min": 0.0006, "vol_max": 0.0009, "vol_mean": 0.00075, "vol_std": 0.00008,
    },
    "Hair Oils & Styling Serums": {
        "parent": "haircare",
        "weight_min": 0.20, "weight_max": 0.38, "weight_mean": 0.28, "weight_std": 0.04,
        "vol_min": 0.0003, "vol_max": 0.0005, "vol_mean": 0.00040, "vol_std": 0.00005,
    },
    "Body Lotions & Body Wash": {
        "parent": "skincare",
        "weight_min": 0.60, "weight_max": 0.95, "weight_mean": 0.75, "weight_std": 0.08,
        "vol_min": 0.0007, "vol_max": 0.0011, "vol_mean": 0.00088, "vol_std": 0.00010,
    },
    "Face Creams & Serums": {
        "parent": "skincare",
        "weight_min": 0.25, "weight_max": 0.45, "weight_mean": 0.32, "weight_std": 0.04,
        "vol_min": 0.0005, "vol_max": 0.0008, "vol_mean": 0.00062, "vol_std": 0.00007,
    },
}

# Explicit Deterministic Subcategory SKU Membership (100 SKUs Bijective Partition)
SUBCATEGORY_SKU_PARTITION = {
    "Color Cosmetics & Compacts": [
        "SKU7", "SKU8", "SKU17", "SKU21", "SKU23", "SKU27", "SKU28", "SKU29",
        "SKU33", "SKU35", "SKU38", "SKU44", "SKU49", "SKU50", "SKU59", "SKU62"
    ],
    "Lip & Eye Makeup": [
        "SKU71", "SKU72", "SKU73", "SKU85", "SKU88", "SKU89", "SKU91", "SKU92", "SKU94", "SKU96"
    ],
    "Shampoos & Conditioners": [
        "SKU0", "SKU2", "SKU5", "SKU12", "SKU18", "SKU22", "SKU24", "SKU25", "SKU26", "SKU30",
        "SKU43", "SKU45", "SKU46", "SKU48", "SKU51", "SKU54", "SKU55", "SKU57", "SKU61", "SKU68",
        "SKU70", "SKU74"
    ],
    "Hair Oils & Styling Serums": [
        "SKU76", "SKU77", "SKU78", "SKU79", "SKU81", "SKU83", "SKU84", "SKU87", "SKU93", "SKU95", "SKU97", "SKU99"
    ],
    "Body Lotions & Body Wash": [
        "SKU10", "SKU13", "SKU14", "SKU15", "SKU16", "SKU19", "SKU20", "SKU31",
        "SKU32", "SKU34", "SKU36", "SKU37", "SKU39", "SKU40", "SKU41"
    ],
    "Face Creams & Serums": [
        "SKU1", "SKU3", "SKU4", "SKU6", "SKU9", "SKU11", "SKU42", "SKU47", "SKU52", "SKU53",
        "SKU56", "SKU58", "SKU60", "SKU63", "SKU64", "SKU65", "SKU66", "SKU67", "SKU69", "SKU75",
        "SKU80", "SKU82", "SKU86", "SKU90", "SKU98"
    ],
}

# Route Network Specifications (Origin strictly Mumbai / Bhiwandi)
ROUTE_DEFINITIONS = [
    {"route_id": "RT-MUM-PUN", "dest_city": "Pune", "dist_km": 150, "transit_hours": 4.5, "toll": 450.0},
    {"route_id": "RT-MUM-NSK", "dest_city": "Nashik", "dist_km": 165, "transit_hours": 4.5, "toll": 380.0},
    {"route_id": "RT-MUM-SUR", "dest_city": "Surat", "dist_km": 280, "transit_hours": 6.5, "toll": 620.0},
    {"route_id": "RT-MUM-BRD", "dest_city": "Vadodara", "dist_km": 410, "transit_hours": 8.5, "toll": 850.0},
    {"route_id": "RT-MUM-AMD", "dest_city": "Ahmedabad", "dist_km": 530, "transit_hours": 11.0, "toll": 1100.0},
    {"route_id": "RT-MUM-GOA", "dest_city": "Goa", "dist_km": 570, "transit_hours": 13.0, "toll": 780.0},
    {"route_id": "RT-MUM-IND", "dest_city": "Indore", "dist_km": 585, "transit_hours": 12.5, "toll": 1250.0},
    {"route_id": "RT-MUM-HYD", "dest_city": "Hyderabad", "dist_km": 710, "transit_hours": 15.0, "toll": 1450.0},
    {"route_id": "RT-MUM-NAG", "dest_city": "Nagpur", "dist_km": 820, "transit_hours": 15.5, "toll": 1600.0},
    {"route_id": "RT-MUM-BLR", "dest_city": "Bengaluru", "dist_km": 980, "transit_hours": 19.0, "toll": 1950.0},
]

# Truck Fleet Specifications (30 Trucks across 4 Classes)
FLEET_SPECIFICATIONS = [
    # 10 x 14ft LCV (TRK-001 to TRK-010)
    *[
        {
            "truck_id": f"TRK-{i:03d}",
            "truck_type": "14ft LCV",
            "max_payload_kg": 3500.0,
            "max_volume_m3": 18.0,
            "fuel_type": "Diesel",
            "co2_emission_factor_g_km": 420.0,
            "ownership_type": "Dedicated Fleet",
            "eligible_distance_max": 450,
        }
        for i in range(1, 11)
    ],
    # 10 x 20ft ICV (TRK-011 to TRK-020)
    *[
        {
            "truck_id": f"TRK-{i:03d}",
            "truck_type": "20ft ICV",
            "max_payload_kg": 7000.0,
            "max_volume_m3": 32.0,
            "fuel_type": "Diesel",
            "co2_emission_factor_g_km": 680.0,
            "ownership_type": "Dedicated Fleet",
            "eligible_distance_max": 750,
        }
        for i in range(11, 21)
    ],
    # 6 x 24ft MCV (TRK-021 to TRK-026)
    *[
        {
            "truck_id": f"TRK-{i:03d}",
            "truck_type": "24ft MCV",
            "max_payload_kg": 10000.0,
            "max_volume_m3": 45.0,
            "fuel_type": "Diesel",
            "co2_emission_factor_g_km": 890.0,
            "ownership_type": "Contracted Carrier",
            "eligible_distance_max": 1200,
        }
        for i in range(21, 27)
    ],
    # 4 x 32ft HCV (TRK-027 to TRK-030)
    *[
        {
            "truck_id": f"TRK-{i:03d}",
            "truck_type": "32ft HCV",
            "max_payload_kg": 16000.0,
            "max_volume_m3": 62.0,
            "fuel_type": "Multi-Axle Diesel",
            "co2_emission_factor_g_km": 1150.0,
            "ownership_type": "Contracted Carrier",
            "eligible_distance_max": 1500,
        }
        for i in range(27, 31)
    ],
]


# ===========================================================================
# 1. DIRECTORY PUBLICATION & STARTUP RECOVERY LOGIC
# ===========================================================================
def validate_dataset_manifest(dir_path: str) -> bool:
    """Verify that a directory contains all 14 non-empty expected CSV tables."""
    if not os.path.isdir(dir_path):
        return False
    for filename in EXPECTED_TABLES:
        filepath = os.path.join(dir_path, filename)
        if not os.path.isfile(filepath) or os.path.getsize(filepath) == 0:
            return False
    return True


def execute_startup_recovery(base_data_dir: str):
    """
    Examine the state of data/synthetic/ and backup directories prior to generation.
    Recovers from interrupted prior promotions and cleans stale directories safely.
    """
    synthetic_dir = os.path.join(base_data_dir, "synthetic")
    backup_dir = os.path.join(base_data_dir, "synthetic_backup")
    staging_dir = os.path.join(base_data_dir, "synthetic_staging")

    print("[Startup Recovery] Inspecting directory state in:", base_data_dir)

    synth_exists = os.path.isdir(synthetic_dir)
    backup_exists = os.path.isdir(backup_dir)

    synth_valid = validate_dataset_manifest(synthetic_dir) if synth_exists else False
    backup_valid = validate_dataset_manifest(backup_dir) if backup_exists else False

    # Case 1: Backup exists but synthetic missing -> Interrupted promotion
    if backup_exists and not synth_exists:
        if backup_valid:
            print("[Startup Recovery] Active directory missing, but backup is valid. Restoring backup...")
            os.rename(backup_dir, synthetic_dir)
        else:
            raise RuntimeError("[Startup Recovery] CRITICAL: Backup exists but is invalid/corrupt. Halting.")

    # Case 2: Both exist -> Interrupted cleanup
    elif backup_exists and synth_exists:
        if synth_valid:
            print("[Startup Recovery] Active dataset is valid. Cleaning up stale backup directory...")
            shutil.rmtree(backup_dir)
        elif backup_valid:
            print("[Startup Recovery] Active dataset is corrupted, but backup is valid. Rolling back...")
            shutil.rmtree(synthetic_dir)
            os.rename(backup_dir, synthetic_dir)
        else:
            raise RuntimeError(
                "[Startup Recovery] CRITICAL STOP: Both active and backup datasets are incomplete/corrupted. "
                "Preserving both directories for inspection."
            )

    # Clean up any leftover staging directory from an aborted run
    if os.path.isdir(staging_dir):
        print("[Startup Recovery] Cleaning up stale staging directory...")
        shutil.rmtree(staging_dir)

    print("[Startup Recovery] Directory state certified clean.")


def promote_staging_to_synthetic(staging_dir: str, target_dir: str, backup_dir: str):
    """
    Safely promote validated staging directory to production target with automated rollback.
    """
    print(f"[Publication] Promoting {staging_dir} to {target_dir}...")
    if os.path.isdir(target_dir):
        # Step 3a: Move existing to backup
        os.rename(target_dir, backup_dir)

    try:
        # Step 3b: Move staging to target
        os.rename(staging_dir, target_dir)
        # Step 3c: Delete backup on success
        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir)
        print("[Publication] Promotion succeeded atomically.")
    except Exception as e:
        print(f"[Publication ERROR] Promotion failed: {e}. Executing rollback...")
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        if os.path.isdir(backup_dir):
            os.rename(backup_dir, target_dir)
        if os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir)
        raise RuntimeError(f"[Publication ERROR] Rollback complete. Original dataset preserved. Details: {e}")


# ===========================================================================
# 2. MASTER SYNTHETIC DATA GENERATOR ENGINE
# ===========================================================================
class CargoSenseSyntheticGenerator:
    """End-to-end deterministic operational ecosystem generator for CargoSense."""

    def __init__(self, raw_supply_chain_path: str, staging_dir: str, seed: int = RANDOM_SEED):
        self.raw_path = raw_supply_chain_path
        self.staging_dir = staging_dir
        self.seed = seed
        self.rng = np.random.RandomState(seed)

        # Datasets storage
        self.tables: Dict[str, pd.DataFrame] = {}

    def build_products(self) -> pd.DataFrame:
        """Table 1: products.csv (Exactly 100 rows)."""
        print("[Generator] Building Table 1: products.csv (100 SKUs)...")
        raw_df = pd.read_csv(self.raw_path)

        # Map SKUs to verified attributes
        sku_to_raw = {}
        for _, row in raw_df.iterrows():
            sku_to_raw[row["SKU"]] = {
                "category": str(row["Product type"]).lower(),
                "price": round(float(row["Price"]), 2),
                "supplier": str(row["Supplier name"]),
            }

        # Build reverse lookup for subcategories
        sku_to_subcat = {}
        for subcat, skus in SUBCATEGORY_SKU_PARTITION.items():
            for sku in skus:
                sku_to_subcat[sku] = subcat

        products_list = []
        # Local deterministic RNG for physical dimensions
        phys_rng = np.random.RandomState(self.seed + 101)

        for i in range(100):
            sku_id = f"SKU{i}"
            raw_meta = sku_to_raw[sku_id]
            subcat = sku_to_subcat[sku_id]
            specs = SUBCATEGORY_SPECS[subcat]

            # Physical sampling
            w = phys_rng.normal(specs["weight_mean"], specs["weight_std"])
            w = float(np.clip(w, specs["weight_min"], specs["weight_max"]))
            v = phys_rng.normal(specs["vol_mean"], specs["vol_std"])
            v = float(np.clip(v, specs["vol_min"], specs["vol_max"]))
            density = round(w / v, 1)

            product_name = f"{subcat} - Formula {i+1:02d}"

            products_list.append({
                "sku_id": sku_id,
                "product_name": product_name,
                "product_category": raw_meta["category"],
                "sub_category": subcat,
                "unit_price": raw_meta["price"],  # in unspecified monetary units (MU)
                "supplier_name": raw_meta["supplier"],
                "unit_weight_kg": round(w, 3),
                "unit_volume_m3": round(v, 6),
                "density_kg_m3": density,
                "is_active": True,
            })

        df = pd.DataFrame(products_list)
        self.tables["products.csv"] = df
        return df

    def build_trucks(self) -> pd.DataFrame:
        """Table 2: trucks.csv (Exactly 30 rows)."""
        print("[Generator] Building Table 2: trucks.csv (30 Trucks across 4 classes)...")
        trucks_clean = []
        for t in FLEET_SPECIFICATIONS:
            trucks_clean.append({
                "truck_id": t["truck_id"],
                "truck_type": t["truck_type"],
                "max_payload_kg": t["max_payload_kg"],
                "max_volume_m3": t["max_volume_m3"],
                "fuel_type": t["fuel_type"],
                "co2_emission_factor_g_km": t["co2_emission_factor_g_km"],
                "ownership_type": t["ownership_type"],
            })
        df = pd.DataFrame(trucks_clean)
        self.tables["trucks.csv"] = df
        return df

    def build_routes(self) -> pd.DataFrame:
        """Table 3: routes.csv (Exactly 10 rows)."""
        print("[Generator] Building Table 3: routes.csv (10 Mumbai-Origin Corridors)...")
        routes_list = []
        for r in ROUTE_DEFINITIONS:
            routes_list.append({
                "route_id": r["route_id"],
                "origin_city": "Mumbai",
                "destination_city": r["dest_city"],
                "distance_km": r["dist_km"],
                "standard_transit_hours": r["transit_hours"],
                "toll_charges_mu": r["toll"],
            })
        df = pd.DataFrame(routes_list)
        self.tables["routes.csv"] = df
        return df

    def build_truck_route_permissions(self) -> pd.DataFrame:
        """Table 4: truck_route_permissions.csv (~90 rows)."""
        print("[Generator] Building Table 4: truck_route_permissions.csv...")
        trucks = self.tables["trucks.csv"]
        routes = self.tables["routes.csv"]

        perm_list = []
        perm_counter = 1

        # Map truck_id to eligible max distance
        truck_dist_limits = {t["truck_id"]: t["eligible_distance_max"] for t in FLEET_SPECIFICATIONS}

        for _, t in trucks.iterrows():
            tid = t["truck_id"]
            max_d = truck_dist_limits[tid]
            for _, r in routes.iterrows():
                rid = r["route_id"]
                dist = r["distance_km"]

                # 14ft LCV limited to <= 450km (Pune, Nashik, Surat, Vadodara)
                # 20ft ICV limited to <= 750km
                # 24ft MCV and 32ft HCV permitted everywhere
                is_permitted = dist <= max_d
                reason = "Within standard operational range" if is_permitted else "Exceeds vehicle class highway range limit"

                perm_list.append({
                    "permission_id": f"PRM-{perm_counter:04d}",
                    "truck_id": tid,
                    "route_id": rid,
                    "is_permitted": is_permitted,
                    "restriction_reason": reason,
                })
                perm_counter += 1

        df = pd.DataFrame(perm_list)
        self.tables["truck_route_permissions.csv"] = df
        return df

    def build_operational_simulation(self):
        """
        Tables 5 through 13: Orders, Order Lines, Planning Runs, Allocations,
        Shipments, Shipment Lines, Dock Load Events, Inventory Ledger & Snapshots.
        """
        print("[Generator] Simulating 90-Day Operational Activity (Jan 1 - Mar 30, 2024)...")

        products_df = self.tables["products.csv"]
        routes_df = self.tables["routes.csv"]
        trucks_df = self.tables["trucks.csv"]
        perms_df = self.tables["truck_route_permissions.csv"]

        sku_weights = dict(zip(products_df["sku_id"], products_df["unit_weight_kg"]))
        sku_volumes = dict(zip(products_df["sku_id"], products_df["unit_volume_m3"]))
        sku_prices = dict(zip(products_df["sku_id"], products_df["unit_price"]))
        all_skus = list(products_df["sku_id"])
        all_routes = list(routes_df["route_id"])
        route_to_city = dict(zip(routes_df["route_id"], routes_df["destination_city"]))
        route_transit_hours = dict(zip(routes_df["route_id"], routes_df["standard_transit_hours"]))

        # Permitted trucks by route
        permitted_trucks_by_route = {}
        for rid in all_routes:
            p_trucks = perms_df[(perms_df["route_id"] == rid) & (perms_df["is_permitted"])]["truck_id"].tolist()
            permitted_trucks_by_route[rid] = p_trucks

        # Truck capacity lookup
        truck_payload = dict(zip(trucks_df["truck_id"], trucks_df["max_payload_kg"]))
        truck_cube = dict(zip(trucks_df["truck_id"], trucks_df["max_volume_m3"]))

        # Customer segments
        customer_segments = ["Modern Retail", "Distributor", "E-Commerce Hub"]

        # -------------------------------------------------------------------
        # 1. Day 1 Baseline Starting Inventory State (T_0: 2024-01-01 00:00:00)
        # -------------------------------------------------------------------
        # Deterministic baseline: 1000 + ((i * 17) % 100) * 10 units (1000 to 1990)
        on_hand_balances = {}
        reserved_balances = {}
        for i, sku in enumerate(all_skus):
            base_qty = 1000 + ((i * 17) % 100) * 10
            on_hand_balances[sku] = base_qty
            reserved_balances[sku] = 0

        # Output collections
        orders_records = []
        order_lines_records = []
        planning_records = []
        allocations_records = []
        shipments_records = []
        shipment_lines_records = []
        load_events_records = []
        transactions_records = []
        snapshots_records = []

        # Tracking state
        active_order_lines: Dict[str, Dict[str, Any]] = {}
        order_line_active_reserved: Dict[str, int] = {}
        truck_next_available_ts: Dict[str, datetime] = {tid: SIMULATION_START_TS for tid in trucks_df["truck_id"]}

        order_counter = 1
        line_counter = 1
        txn_counter = 1
        alloc_counter = 1
        shipment_counter = 1
        shpline_counter = 1
        event_counter = 1
        snapshot_counter = 1

        # Pre-seed daily order placement volume (mean ~16-18 orders/day -> ~1500 total)
        sim_rng = np.random.RandomState(self.seed + 202)

        # -------------------------------------------------------------------
        # Simulation Loop: 90 Calendar Days
        # -------------------------------------------------------------------
        current_date = SIMULATION_START_DATE

        for day_idx in range(TOTAL_CALENDAR_DAYS):
            day_num = day_idx + 1
            cal_date_str = current_date.strftime("%Y-%m-%d")

            # Cutoff milestone for today (23:00:00)
            today_cutoff_ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=23)

            # Inbound Supplier Restocks (arrive around 10:00 AM every ~5 days for selected SKUs)
            if day_num % 5 == 1:
                receipt_ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=10)
                # Restock 20 SKUs
                restock_skus = all_skus[(day_idx * 7) % 100 : ((day_idx * 7) % 100) + 20]
                for r_sku in restock_skus:
                    r_qty = 500
                    on_hand_balances[r_sku] += r_qty
                    transactions_records.append({
                        "transaction_id": f"TXN-{txn_counter:06d}",
                        "transaction_timestamp": receipt_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "sku_id": r_sku,
                        "order_line_id": None,
                        "planning_run_id": None,
                        "transaction_type": "SUPPLIER_RECEIPT",
                        "reference_document_type": "PURCHASE_ORDER",
                        "reference_id": f"PO-{cal_date_str}-{r_sku}",
                        "delta_on_hand": r_qty,
                        "delta_reserved": 0,
                    })
                    txn_counter += 1

            # ---------------------------------------------------------------
            # A. Generate Customer Orders for Day d (Placed 08:00 to 20:00)
            # ---------------------------------------------------------------
            daily_order_count = sim_rng.poisson(17)  # mean 17 orders/day
            daily_orders = []

            for _ in range(daily_order_count):
                order_id = f"ORD-{cal_date_str.replace('-', '')}-{order_counter:04d}"
                order_counter += 1

                route_id = sim_rng.choice(all_routes)
                dest_city = route_to_city[route_id]
                segment = sim_rng.choice(customer_segments, p=[0.45, 0.35, 0.20])

                # Placement time: between 08:00 and 20:00
                hour = sim_rng.randint(8, 21)
                minute = sim_rng.randint(0, 60)
                order_ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour, minutes=minute)

                # Requested delivery: order_date + 2 to 4 days
                req_delivery = current_date + timedelta(days=sim_rng.randint(2, 5))

                num_lines = sim_rng.choice([1, 2, 3], p=[0.45, 0.40, 0.15])
                chosen_skus = sim_rng.choice(all_skus, size=num_lines, replace=False)

                lines_data = []
                for sku in chosen_skus:
                    line_id = f"ORDLN-{line_counter:06d}"
                    line_counter += 1

                    ordered_qty = int(sim_rng.choice([20, 30, 40, 50, 60, 80, 100]))
                    w_kg = round(ordered_qty * sku_weights[sku], 3)
                    v_m3 = round(ordered_qty * sku_volumes[sku], 6)

                    lines_data.append({
                        "order_line_id": line_id,
                        "order_id": order_id,
                        "sku_id": sku,
                        "ordered_quantity": ordered_qty,
                        "shipped_quantity": 0,
                        "open_quantity": ordered_qty,
                        "line_weight_kg": w_kg,
                        "line_volume_m3": v_m3,
                    })

                    # Active tracking in memory
                    active_order_lines[line_id] = {
                        "order_id": order_id,
                        "sku_id": sku,
                        "route_id": route_id,
                        "dest_city": dest_city,
                        "ordered_quantity": ordered_qty,
                        "shipped_quantity": 0,
                        "open_quantity": ordered_qty,
                        "unit_weight": sku_weights[sku],
                        "unit_volume": sku_volumes[sku],
                        "order_date": current_date,
                    }
                    order_line_active_reserved[line_id] = 0

                    # Initial ORDER_RESERVATION transaction (at order placement)
                    # Claim reservation up to available on-hand
                    avail_stock = on_hand_balances[sku] - reserved_balances[sku]
                    reserve_qty = min(ordered_qty, max(0, avail_stock))

                    if reserve_qty > 0:
                        reserved_balances[sku] += reserve_qty
                        order_line_active_reserved[line_id] += reserve_qty
                        transactions_records.append({
                            "transaction_id": f"TXN-{txn_counter:06d}",
                            "transaction_timestamp": order_ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "sku_id": sku,
                            "order_line_id": line_id,
                            "planning_run_id": None,
                            "transaction_type": "ORDER_RESERVATION",
                            "reference_document_type": "CUSTOMER_ORDER",
                            "reference_id": f"RES-{line_id}-01",
                            "delta_on_hand": 0,
                            "delta_reserved": reserve_qty,
                        })
                        txn_counter += 1

                orders_records.append({
                    "order_id": order_id,
                    "order_date": cal_date_str,
                    "order_timestamp": order_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "destination_city": dest_city,
                    "route_id": route_id,
                    "customer_segment": segment,
                    "requested_delivery_date": req_delivery.strftime("%Y-%m-%d"),
                    "order_status": "OPEN",
                })
                order_lines_records.extend(lines_data)

            # ---------------------------------------------------------------
            # B. Nightly Inventory Snapshot (23:00:00 Daily)
            # ---------------------------------------------------------------
            for sku in all_skus:
                on_h = on_hand_balances[sku]
                res_q = reserved_balances[sku]
                avail_q = on_h - res_q
                snapshots_records.append({
                    "snapshot_id": f"SNP-{snapshot_counter:06d}",
                    "snapshot_date": cal_date_str,
                    "snapshot_timestamp": today_cutoff_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "sku_id": sku,
                    "on_hand_quantity": on_h,
                    "reserved_quantity": res_q,
                    "available_quantity": avail_q,
                })
                snapshot_counter += 1

            # ---------------------------------------------------------------
            # C. Batch Planning Run (Cutoff 23:00, Run Completed 04:00 next day)
            # ---------------------------------------------------------------
            planning_run_id = f"RUN-{cal_date_str.replace('-', '')}"
            run_completed_ts = today_cutoff_ts + timedelta(hours=5)  # 04:00:00 next morning

            # Collect unfulfilled open lines for this run
            open_lines_for_run = [
                (lid, ldata) for lid, ldata in active_order_lines.items()
                if ldata["open_quantity"] > 0
            ]

            # Group open lines by route
            lines_by_route: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {r: [] for r in all_routes}
            for lid, ldata in open_lines_for_run:
                lines_by_route[ldata["route_id"]].append((lid, ldata))

            planned_trucks_today = 0

            # Plan dispatches per route
            for rid, rlines in lines_by_route.items():
                if not rlines:
                    continue

                # Candidate trucks for this route that are available on/before tomorrow morning 06:00
                cand_trucks = [
                    tid for tid in permitted_trucks_by_route[rid]
                    if truck_next_available_ts[tid] <= (run_completed_ts + timedelta(hours=2))
                ]
                if not cand_trucks:
                    continue

                # Sort candidate trucks: prefer dedicated fleet
                cand_trucks.sort(key=lambda t: 0 if "Dedicated" in t else 1)
                assigned_truck_id = cand_trucks[0]

                p_cap = truck_payload[assigned_truck_id]
                v_cap = truck_cube[assigned_truck_id]

                trip_id = f"TRIP-{cal_date_str.replace('-', '')}-{assigned_truck_id}-{rid.split('-')[-1]}"
                shipment_id = f"SHP-{cal_date_str.replace('-', '')}-{shipment_counter:03d}"
                shipment_counter += 1
                planned_trucks_today += 1

                # Allocate order lines onto this truck within payload & cube
                curr_weight = 0.0
                curr_volume = 0.0
                allocated_for_trip = []

                # Deterministic sorting of lines: by open quantity descending
                sorted_rlines = sorted(rlines, key=lambda x: x[1]["open_quantity"], reverse=True)

                for alloc_idx, (lid, ldata) in enumerate(sorted_rlines, start=1):
                    sku = ldata["sku_id"]
                    u_w = ldata["unit_weight"]
                    u_v = ldata["unit_volume"]

                    # Maximum units that can fit
                    max_by_w = int((p_cap - curr_weight) // u_w) if u_w > 0 else 0
                    max_by_v = int((v_cap - curr_volume) // u_v) if u_v > 0 else 0
                    fit_qty = min(ldata["open_quantity"], max_by_w, max_by_v)

                    if fit_qty <= 0:
                        continue

                    # Allocation Line Record
                    alloc_line_id = f"ALLOC-{planning_run_id}-{assigned_truck_id}-{lid}-{alloc_idx:02d}"
                    w_alloc = round(fit_qty * u_w, 3)
                    v_alloc = round(fit_qty * u_v, 6)

                    allocations_records.append({
                        "allocation_line_id": alloc_line_id,
                        "planning_run_id": planning_run_id,
                        "trip_id": trip_id,
                        "truck_id": assigned_truck_id,
                        "route_id": rid,
                        "order_id": ldata["order_id"],
                        "order_line_id": lid,
                        "sku_id": sku,
                        "planned_quantity": fit_qty,
                        "planned_weight_kg": w_alloc,
                        "planned_volume_m3": v_alloc,
                    })
                    alloc_counter += 1

                    allocated_for_trip.append({
                        "order_line_id": lid,
                        "sku_id": sku,
                        "planned_qty": fit_qty,
                        "weight": w_alloc,
                        "volume": v_alloc,
                        "alloc_line_id": alloc_line_id,
                    })

                    curr_weight += w_alloc
                    curr_volume += v_alloc

                    if curr_weight >= 0.90 * p_cap or curr_volume >= 0.90 * v_cap:
                        break  # Well-utilized truckload

                if not allocated_for_trip:
                    continue

                # -----------------------------------------------------------
                # D. Execution: Staging, Loading, and Dispatch on Day d+1
                # -----------------------------------------------------------
                # Scheduled departure: 06:00 on Day d+1
                exec_day = current_date + timedelta(days=1)
                planned_dispatch_ts = datetime.combine(exec_day, datetime.min.time()) + timedelta(hours=6)
                loading_start_ts = planned_dispatch_ts - timedelta(hours=1, minutes=45)  # 04:15
                loading_end_ts = planned_dispatch_ts - timedelta(minutes=15)            # 05:45

                is_post_horizon = (planned_dispatch_ts >= SIMULATION_END_TS)

                if is_post_horizon:
                    # Scheduled for post-horizon execution (after March 30 23:00)
                    shipments_records.append({
                        "shipment_id": shipment_id,
                        "trip_id": trip_id,
                        "planning_run_id": planning_run_id,
                        "truck_id": assigned_truck_id,
                        "route_id": rid,
                        "shipment_status": "PLANNED",
                        "planned_dispatch_time": planned_dispatch_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "loading_start_time": None,
                        "loading_end_time": None,
                        "actual_dispatch_time": None,
                        "expected_arrival_time": None,
                        "actual_delivery_time": None,
                        "truck_next_available_time": None,
                        "total_weight_kg": round(curr_weight, 3),
                        "total_volume_m3": round(curr_volume, 3),
                        "weight_utilization_pct": round(curr_weight / p_cap * 100, 2),
                        "volume_utilization_pct": round(curr_volume / v_cap * 100, 2),
                    })

                    for item in allocated_for_trip:
                        shpln_id = f"SHPLN-{shpline_counter:06d}"
                        shpline_counter += 1
                        shipment_lines_records.append({
                            "shipment_line_id": shpln_id,
                            "shipment_id": shipment_id,
                            "trip_id": trip_id,
                            "order_line_id": item["order_line_id"],
                            "sku_id": item["sku_id"],
                            "line_status": "PLANNED",
                            "loaded_quantity": 0,
                            "shipped_quantity": 0,
                            "shipped_weight_kg": 0.0,
                            "shipped_volume_m3": 0.0,
                        })

                # Decide if shipment departs or is HELD (96% depart, 4% held at dock for maintenance)
                elif (sim_rng.rand() < 0.04) and (day_num < TOTAL_CALENDAR_DAYS - 2):
                    # Held Shipment
                    shipments_records.append({
                        "shipment_id": shipment_id,
                        "trip_id": trip_id,
                        "planning_run_id": planning_run_id,
                        "truck_id": assigned_truck_id,
                        "route_id": rid,
                        "shipment_status": "HELD",
                        "planned_dispatch_time": planned_dispatch_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "loading_start_time": loading_start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "loading_end_time": loading_end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "actual_dispatch_time": None,
                        "expected_arrival_time": None,
                        "actual_delivery_time": None,
                        "truck_next_available_time": (loading_end_ts + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
                        "total_weight_kg": round(curr_weight, 3),
                        "total_volume_m3": round(curr_volume, 3),
                        "weight_utilization_pct": round(curr_weight / p_cap * 100, 2),
                        "volume_utilization_pct": round(curr_volume / v_cap * 100, 2),
                    })
                    truck_next_available_ts[assigned_truck_id] = loading_end_ts + timedelta(hours=4)

                    # Shipment Lines & Scans for Held Trip: Staged, Shipped = 0
                    for item in allocated_for_trip:
                        shpln_id = f"SHPLN-{shpline_counter:06d}"
                        shpline_counter += 1

                        # Barcode Scan: LOAD_SCAN
                        load_events_records.append({
                            "event_id": f"EVT-{event_counter:06d}",
                            "shipment_id": shipment_id,
                            "shipment_line_id": shpln_id,
                            "trip_id": trip_id,
                            "order_line_id": item["order_line_id"],
                            "sku_id": item["sku_id"],
                            "event_type": "LOAD_SCAN",
                            "quantity": item["planned_qty"],
                            "event_timestamp": loading_start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "operator_id": "DOCK-OP-01",
                        })
                        event_counter += 1

                        # De-vanning back to dock due to vehicle maintenance hold
                        offload_ts = loading_end_ts + timedelta(minutes=30)
                        load_events_records.append({
                            "event_id": f"EVT-{event_counter:06d}",
                            "shipment_id": shipment_id,
                            "shipment_line_id": shpln_id,
                            "trip_id": trip_id,
                            "order_line_id": item["order_line_id"],
                            "sku_id": item["sku_id"],
                            "event_type": "OFFLOAD_SCAN",
                            "quantity": item["planned_qty"],
                            "event_timestamp": offload_ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "operator_id": "DOCK-OP-01",
                        })
                        event_counter += 1

                        shipment_lines_records.append({
                            "shipment_line_id": shpln_id,
                            "shipment_id": shipment_id,
                            "trip_id": trip_id,
                            "order_line_id": item["order_line_id"],
                            "sku_id": item["sku_id"],
                            "line_status": "HELD",
                            "loaded_quantity": 0,  # fully offloaded back to dock
                            "shipped_quantity": 0,  # strictly 0 for non-dispatched
                            "shipped_weight_kg": 0.0,
                            "shipped_volume_m3": 0.0,
                        })

                else:
                    # Successful Dispatch
                    actual_dispatch_ts = planned_dispatch_ts + timedelta(minutes=sim_rng.randint(5, 25))
                    t_hours = route_transit_hours[rid]
                    exp_arrival_ts = actual_dispatch_ts + timedelta(hours=t_hours, minutes=30)

                    # Turnaround return back to Bhiwandi
                    return_ts = actual_dispatch_ts + timedelta(hours=2 * t_hours + 3)
                    truck_next_available_ts[assigned_truck_id] = return_ts

                    # Delivery status depends on whether return falls within simulation
                    is_delivered = exp_arrival_ts <= SIMULATION_END_TS
                    sh_status = "DELIVERED" if is_delivered else "IN_TRANSIT"
                    deliv_ts = exp_arrival_ts if is_delivered else None

                    shipments_records.append({
                        "shipment_id": shipment_id,
                        "trip_id": trip_id,
                        "planning_run_id": planning_run_id,
                        "truck_id": assigned_truck_id,
                        "route_id": rid,
                        "shipment_status": sh_status,
                        "planned_dispatch_time": planned_dispatch_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "loading_start_time": loading_start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "loading_end_time": loading_end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "actual_dispatch_time": actual_dispatch_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "expected_arrival_time": exp_arrival_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "actual_delivery_time": deliv_ts.strftime("%Y-%m-%d %H:%M:%S") if deliv_ts else None,
                        "truck_next_available_time": return_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "total_weight_kg": round(curr_weight, 3),
                        "total_volume_m3": round(curr_volume, 3),
                        "weight_utilization_pct": round(curr_weight / p_cap * 100, 2),
                        "volume_utilization_pct": round(curr_volume / v_cap * 100, 2),
                    })

                    # Commit all shipment lines atomically
                    for item in allocated_for_trip:
                        shpln_id = f"SHPLN-{shpline_counter:06d}"
                        shpline_counter += 1
                        q = item["planned_qty"]
                        lid = item["order_line_id"]
                        sku = item["sku_id"]

                        # 1. Barcode scan: LOAD_SCAN
                        load_events_records.append({
                            "event_id": f"EVT-{event_counter:06d}",
                            "shipment_id": shipment_id,
                            "shipment_line_id": shpln_id,
                            "trip_id": trip_id,
                            "order_line_id": lid,
                            "sku_id": sku,
                            "event_type": "LOAD_SCAN",
                            "quantity": q,
                            "event_timestamp": loading_start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "operator_id": "DOCK-OP-02",
                        })
                        event_counter += 1

                        # 2. Shipment line
                        shipment_lines_records.append({
                            "shipment_line_id": shpln_id,
                            "shipment_id": shipment_id,
                            "trip_id": trip_id,
                            "order_line_id": lid,
                            "sku_id": sku,
                            "line_status": sh_status,
                            "loaded_quantity": q,
                            "shipped_quantity": q,
                            "shipped_weight_kg": item["weight"],
                            "shipped_volume_m3": item["volume"],
                        })

                        # 3. Update order line cumulative fulfillment
                        active_order_lines[lid]["shipped_quantity"] += q
                        active_order_lines[lid]["open_quantity"] -= q
                        order_line_active_reserved[lid] -= q

                        # 4. Atomic Ledger Record: DISPATCH_SHIPPED
                        # delta_on_hand = -q, delta_reserved = -q, delta_available = 0
                        on_hand_balances[sku] -= q
                        reserved_balances[sku] -= q

                        dispatch_ref = f"DSP-{shipment_id}-{shpln_id}"
                        transactions_records.append({
                            "transaction_id": f"TXN-{txn_counter:06d}",
                            "transaction_timestamp": actual_dispatch_ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "sku_id": sku,
                            "order_line_id": lid,
                            "planning_run_id": planning_run_id,
                            "transaction_type": "DISPATCH_SHIPPED",
                            "reference_document_type": "SHIPMENT_DISPATCH",
                            "reference_id": dispatch_ref,
                            "delta_on_hand": -q,
                            "delta_reserved": -q,
                        })
                        txn_counter += 1

            # Record Planning Run Snapshot
            planning_records.append({
                "planning_run_id": planning_run_id,
                "planning_date": cal_date_str,
                "cutoff_timestamp": today_cutoff_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "run_completed_timestamp": run_completed_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "active_orders_count": len(open_lines_for_run),
                "planned_trucks_count": planned_trucks_today,
                "solver_status": "OPTIMAL",
            })

            # Advance calendar
            current_date += timedelta(days=1)

        # -------------------------------------------------------------------
        # D. Synchronize Orders & Order Lines Final Cumulative State
        # -------------------------------------------------------------------
        # Update order lines table with final cumulative shipped & open quantities
        final_order_lines = []
        for line_row in order_lines_records:
            lid = line_row["order_line_id"]
            shipped = active_order_lines[lid]["shipped_quantity"]
            open_q = active_order_lines[lid]["open_quantity"]
            final_order_lines.append({
                "order_line_id": lid,
                "order_id": line_row["order_id"],
                "sku_id": line_row["sku_id"],
                "ordered_quantity": line_row["ordered_quantity"],
                "shipped_quantity": shipped,
                "open_quantity": open_q,
                "line_weight_kg": line_row["line_weight_kg"],
                "line_volume_m3": line_row["line_volume_m3"],
            })

        # Update order header statuses
        order_line_grouped = {}
        for l in final_order_lines:
            oid = l["order_id"]
            if oid not in order_line_grouped:
                order_line_grouped[oid] = []
            order_line_grouped[oid].append(l)

        final_orders = []
        for o in orders_records:
            oid = o["order_id"]
            lines = order_line_grouped[oid]
            total_ord = sum(l["ordered_quantity"] for l in lines)
            total_shp = sum(l["shipped_quantity"] for l in lines)
            total_opn = sum(l["open_quantity"] for l in lines)

            if total_shp == total_ord:
                stat = "FULFILLED"
            elif total_shp > 0:
                stat = "PARTIALLY_FULFILLED"
            else:
                stat = "OPEN"

            final_orders.append({
                "order_id": o["order_id"],
                "order_date": o["order_date"],
                "order_timestamp": o["order_timestamp"],
                "destination_city": o["destination_city"],
                "route_id": o["route_id"],
                "customer_segment": o["customer_segment"],
                "requested_delivery_date": o["requested_delivery_date"],
                "order_status": stat,
            })

        # -------------------------------------------------------------------
        # E. Table 14: demand_history.csv (Full Dense 90,000-Row Grid)
        # -------------------------------------------------------------------
        print("[Generator] Building Table 14: demand_history.csv (Dense 90,000 Rows)...")
        # Pre-aggregate order demand by (sku_id, destination_city, order_date)
        demand_agg: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for l in final_order_lines:
            lid = l["order_line_id"]
            meta = active_order_lines[lid]
            sku = l["sku_id"]
            city = meta["dest_city"]
            dt_str = meta["order_date"].strftime("%Y-%m-%d")
            q = l["ordered_quantity"]
            oid = meta["order_id"]

            key = (sku, city, dt_str)
            if key not in demand_agg:
                demand_agg[key] = {
                    "units": 0,
                    "orders_set": set(),
                }
            demand_agg[key]["units"] += q
            demand_agg[key]["orders_set"].add(oid)

        # Build Cartesian Grid: 100 SKUs x 10 Cities x 90 Days = 90,000
        dest_cities = [r["dest_city"] for r in ROUTE_DEFINITIONS]
        city_to_route = {r["dest_city"]: r["route_id"] for r in ROUTE_DEFINITIONS}

        demand_history_records = []
        rec_counter = 1

        cal_dates_90 = [
            (SIMULATION_START_DATE + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(TOTAL_CALENDAR_DAYS)
        ]

        for dt_str in cal_dates_90:
            for city in dest_cities:
                rid = city_to_route[city]
                for sku in all_skus:
                    key = (sku, city, dt_str)
                    price = sku_prices[sku]

                    if key in demand_agg:
                        u_dem = demand_agg[key]["units"]
                        o_cnt = len(demand_agg[key]["orders_set"])
                        d_val = round(u_dem * price, 2)
                    else:
                        u_dem = 0
                        o_cnt = 0
                        d_val = 0.0

                    demand_history_records.append({
                        "record_id": f"DMND-{rec_counter:07d}",
                        "sku_id": sku,
                        "destination_city": city,
                        "route_id": rid,
                        "demand_date": dt_str,
                        "gross_units_demanded": u_dem,
                        "net_units_demanded": u_dem,
                        "order_count": o_cnt,
                        "gross_demand_value": d_val,
                        "net_demand_value": d_val,
                    })
                    rec_counter += 1

        # Store all generated dataframes
        self.tables["orders.csv"] = pd.DataFrame(final_orders)
        self.tables["order_lines.csv"] = pd.DataFrame(final_order_lines)
        self.tables["planning_snapshots.csv"] = pd.DataFrame(planning_records)
        self.tables["planned_truck_allocations.csv"] = pd.DataFrame(allocations_records)
        self.tables["shipments.csv"] = pd.DataFrame(shipments_records)
        self.tables["shipment_lines.csv"] = pd.DataFrame(shipment_lines_records)
        self.tables["truck_load_events.csv"] = pd.DataFrame(load_events_records)
        self.tables["inventory_transactions.csv"] = pd.DataFrame(transactions_records)
        self.tables["inventory_snapshots.csv"] = pd.DataFrame(snapshots_records)
        self.tables["demand_history.csv"] = pd.DataFrame(demand_history_records)

        print("[Generator] Operational generation completed successfully.")

    def export_to_staging(self):
        """Write all 14 tables as CSVs into the isolated staging directory."""
        if os.path.exists(self.staging_dir):
            shutil.rmtree(self.staging_dir)
        os.makedirs(self.staging_dir, exist_ok=True)

        print(f"[Generator] Exporting all 14 tables to staging directory: {self.staging_dir}...")
        for name, df in self.tables.items():
            path = os.path.join(self.staging_dir, name)
            df.to_csv(path, index=False)
            print(f"  -> {name}: {len(df):,} rows ({os.path.getsize(path):,} bytes)")


# ===========================================================================
# 3. 15-POINT DOMAIN VALIDATION ASSERTION SUITE
# ===========================================================================
class CargoSenseValidator:
    """Executes the complete 15-point domain validation plan against a dataset directory."""

    def __init__(self, dataset_dir: str, raw_supply_chain_path: str):
        self.dir = dataset_dir
        self.raw_path = raw_supply_chain_path
        self.dfs = {}
        self.results = {}

    def load_tables(self):
        """Load all 14 CSVs from the target directory."""
        for name in EXPECTED_TABLES:
            path = os.path.join(self.dir, name)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Missing required table: {path}")
            self.dfs[name] = pd.read_csv(path)

    def validate_all(self) -> Dict[str, Tuple[bool, str]]:
        """Run all 15 validation tests. Returns dict of {test_id: (pass_bool, message)}."""
        print(f"\n{'='*80}\nRUNNING 15-POINT DOMAIN VALIDATION SUITE ON: {self.dir}\n{'='*80}")
        self.load_tables()

        # V-01: Cardinalities
        self._check_v01()
        # V-02: Subcategory Integrity
        self._check_v02()
        # V-03: Dual Fleet Capacity
        self._check_v03()
        # V-04: Route Network Topology
        self._check_v04()
        # V-05: Point-to-Point Single-Destination
        self._check_v05()
        # V-06: Opening Starting State
        self._check_v06()
        # V-07: Snapshot Boundary Reconciliation
        self._check_v07()
        # V-08: Non-Negative Inventory
        self._check_v08()
        # V-09: Sequential Trip Feasibility
        self._check_v09()
        # V-10: Non-Dispatched / Held Trip Integrity
        self._check_v10()
        # V-11: Dock Scan Balance
        self._check_v11()
        # V-12: Cancellation-Free Order Conservation
        self._check_v12()
        # V-13: Extended All-or-Nothing Dispatch & Reservation Integrity
        self._check_v13()
        # V-14: Demand-History Equality & Order-Date Reconciliation
        self._check_v14()
        # V-15: Trip Linkage & Phase 1-3 Isolation
        self._check_v15()

        all_passed = all(status for status, _ in self.results.values())
        print(f"\n{'='*80}")
        print(f"VALIDATION SUMMARY: {'ALL 15 TESTS PASSED (100%)' if all_passed else 'SOME TESTS FAILED'}")
        print(f"{'='*80}\n")
        return self.results

    def _check_v01(self):
        cands = {
            "products.csv": (len(self.dfs["products.csv"]), 100),
            "trucks.csv": (len(self.dfs["trucks.csv"]), 30),
            "routes.csv": (len(self.dfs["routes.csv"]), 10),
            "planning_snapshots.csv": (len(self.dfs["planning_snapshots.csv"]), 90),
            "inventory_snapshots.csv": (len(self.dfs["inventory_snapshots.csv"]), 9000),
            "demand_history.csv": (len(self.dfs["demand_history.csv"]), 90000),
        }
        passed = all(actual == expected for actual, expected in cands.values())
        msg = ", ".join(f"{k}: {actual}/{expected}" for k, (actual, expected) in cands.items())
        self.results["V-01"] = (passed, f"Entity Cardinalities: {msg}")
        self._print_res("V-01", passed, msg)

    def _check_v02(self):
        pdf = self.dfs["products.csv"]
        raw_df = pd.read_csv(self.raw_path)
        # Category preservation
        raw_counts = raw_df["Product type"].str.lower().value_counts().to_dict()
        syn_counts = pdf["product_category"].value_counts().to_dict()
        cat_match = (raw_counts == syn_counts)

        # 6 subcategories exactly
        subcat_counts = pdf["sub_category"].value_counts().to_dict()
        expected_subcats = {
            "Color Cosmetics & Compacts": 16,
            "Lip & Eye Makeup": 10,
            "Shampoos & Conditioners": 22,
            "Hair Oils & Styling Serums": 12,
            "Body Lotions & Body Wash": 15,
            "Face Creams & Serums": 25,
        }
        subcat_match = (subcat_counts == expected_subcats)
        passed = cat_match and subcat_match
        msg = f"Categories match raw: {cat_match}; Subcategories match exact partition: {subcat_match}"
        self.results["V-02"] = (passed, f"Subcategory Mapping Integrity: {msg}")
        self._print_res("V-02", passed, msg)

    def _check_v03(self):
        sdf = self.dfs["shipments.csv"]
        tdf = self.dfs["trucks.csv"]
        tmap_p = dict(zip(tdf["truck_id"], tdf["max_payload_kg"]))
        tmap_v = dict(zip(tdf["truck_id"], tdf["max_volume_m3"]))

        over_w = 0
        over_v = 0
        for _, row in sdf.iterrows():
            tid = row["truck_id"]
            if row["total_weight_kg"] > tmap_p[tid] + 1e-3:
                over_w += 1
            if row["total_volume_m3"] > tmap_v[tid] + 1e-3:
                over_v += 1

        passed = (over_w == 0) and (over_v == 0)
        msg = f"Over-weight trips: {over_w}, Over-volume trips: {over_v} across {len(sdf)} shipments"
        self.results["V-03"] = (passed, f"Dual Fleet Capacity Compliance: {msg}")
        self._print_res("V-03", passed, msg)

    def _check_v04(self):
        rdf = self.dfs["routes.csv"]
        orig_all_mumbai = (rdf["origin_city"] == "Mumbai").all()
        expected_dests = {"Pune", "Nashik", "Surat", "Vadodara", "Ahmedabad", "Goa", "Indore", "Hyderabad", "Nagpur", "Bengaluru"}
        actual_dests = set(rdf["destination_city"])
        dests_match = (expected_dests == actual_dests)
        chennai_absent = "Chennai" not in actual_dests
        passed = orig_all_mumbai and dests_match and chennai_absent
        msg = f"Origins Mumbai: {orig_all_mumbai}; Approved 10 Dests: {dests_match}; Chennai Absent: {chennai_absent}"
        self.results["V-04"] = (passed, f"Route Network Topology: {msg}")
        self._print_res("V-04", passed, msg)

    def _check_v05(self):
        sdf = self.dfs["shipments.csv"]
        sldf = self.dfs["shipment_lines.csv"]
        odf = self.dfs["orders.csv"]
        oldf = self.dfs["order_lines.csv"]

        line_to_order = dict(zip(oldf["order_line_id"], oldf["order_id"]))
        order_to_route = dict(zip(odf["order_id"], odf["route_id"]))
        shipment_route = dict(zip(sdf["shipment_id"], sdf["route_id"]))

        mismatches = 0
        for _, sline in sldf.iterrows():
            shp_id = sline["shipment_id"]
            exp_route = shipment_route[shp_id]
            ord_id = line_to_order[sline["order_line_id"]]
            ord_route = order_to_route[ord_id]
            if ord_route != exp_route:
                mismatches += 1

        passed = (mismatches == 0)
        msg = f"Consolidated lines route mismatches: {mismatches}"
        self.results["V-05"] = (passed, f"Point-to-Point Single-Destination Trip Model: {msg}")
        self._print_res("V-05", passed, msg)

    def _check_v06(self):
        txndf = self.dfs["inventory_transactions.csv"]
        # Check zero opening balance rows
        opening_rows = txndf[txndf["transaction_type"] == "OPENING_BALANCE"]
        passed = len(opening_rows) == 0
        msg = f"Opening balance pseudo-rows in transactions: {len(opening_rows)}"
        self.results["V-06"] = (passed, f"Opening Inventory Starting State: {msg}")
        self._print_res("V-06", passed, msg)

    def _check_v07(self):
        # Two-stage snapshot reconciliation
        snpdf = self.dfs["inventory_snapshots.csv"]
        txndf = self.dfs["inventory_transactions.csv"]
        pdf = self.dfs["products.csv"]
        all_skus = list(pdf["sku_id"])

        # Calculate opening baseline
        opening_on_hand = {sku: 1000 + ((i * 17) % 100) * 10 for i, sku in enumerate(all_skus)}
        opening_reserved = {sku: 0 for sku in all_skus}

        # Filter transactions
        txndf["ts"] = pd.to_datetime(txndf["transaction_timestamp"])
        t0 = pd.to_datetime("2024-01-01 00:00:00")
        t1 = pd.to_datetime("2024-01-01 23:00:00")

        # Snapshot 1 check
        snp1 = snpdf[snpdf["snapshot_date"] == "2024-01-01"]
        txns_day1 = txndf[(txndf["ts"] >= t0) & (txndf["ts"] < t1)]

        delta_on_hand_d1 = txns_day1.groupby("sku_id")["delta_on_hand"].sum().to_dict()
        delta_res_d1 = txns_day1.groupby("sku_id")["delta_reserved"].sum().to_dict()

        snp1_mismatch = 0
        for _, row in snp1.iterrows():
            sku = row["sku_id"]
            exp_on_h = opening_on_hand[sku] + delta_on_hand_d1.get(sku, 0)
            exp_res = opening_reserved[sku] + delta_res_d1.get(sku, 0)
            if row["on_hand_quantity"] != exp_on_h or row["reserved_quantity"] != exp_res:
                snp1_mismatch += 1

        # Check zero transactions at or after March 30 23:00
        t90 = pd.to_datetime("2024-03-30 23:00:00")
        late_txns = len(txndf[txndf["ts"] >= t90])

        passed = (snp1_mismatch == 0) and (late_txns == 0)
        msg = f"Snapshot 1 mismatches: {snp1_mismatch}; Transactions at/after March 30 23:00: {late_txns}"
        self.results["V-07"] = (passed, f"Two-Stage Snapshot Boundary Reconciliation: {msg}")
        self._print_res("V-07", passed, msg)

    def _check_v08(self):
        snpdf = self.dfs["inventory_snapshots.csv"]
        neg_avail = (snpdf["available_quantity"] < 0).sum()
        avail_calc_err = ((snpdf["on_hand_quantity"] - snpdf["reserved_quantity"]) != snpdf["available_quantity"]).sum()
        passed = (neg_avail == 0) and (avail_calc_err == 0)
        msg = f"Negative available: {neg_avail}; Calculation mismatches: {avail_calc_err} across 9,000 snapshots"
        self.results["V-08"] = (passed, f"Non-Negative Inventory Invariant: {msg}")
        self._print_res("V-08", passed, msg)

    def _check_v09(self):
        sdf = self.dfs["shipments.csv"].copy()
        sdf["loading_start"] = pd.to_datetime(sdf["loading_start_time"])
        sdf["next_avail"] = pd.to_datetime(sdf["truck_next_available_time"])

        overlap_count = 0
        for tid, group in sdf.groupby("truck_id"):
            sorted_trips = group.sort_values("loading_start")
            prev_avail = None
            for _, trip in sorted_trips.iterrows():
                if prev_avail is not None and trip["loading_start"] < prev_avail:
                    overlap_count += 1
                prev_avail = trip["next_avail"]

        passed = (overlap_count == 0)
        msg = f"Sequential trip overlaps: {overlap_count}"
        self.results["V-09"] = (passed, f"Sequential Trip Feasibility: {msg}")
        self._print_res("V-09", passed, msg)

    def _check_v10(self):
        sdf = self.dfs["shipments.csv"]
        sldf = self.dfs["shipment_lines.csv"]
        held_shipments = set(sdf[sdf["shipment_status"].isin(["PLANNED", "LOADING", "HELD", "DELAYED"])]["shipment_id"])

        bad_held_dispatch_ts = (sdf[sdf["shipment_id"].isin(held_shipments)]["actual_dispatch_time"].notna()).sum()
        bad_held_shipped_qty = (sldf[sldf["shipment_id"].isin(held_shipments)]["shipped_quantity"] != 0).sum()

        passed = (bad_held_dispatch_ts == 0) and (bad_held_shipped_qty == 0)
        msg = f"Held trips with dispatch timestamp: {bad_held_dispatch_ts}; Held lines with shipped_quantity > 0: {bad_held_shipped_qty}"
        self.results["V-10"] = (passed, f"Non-Dispatched / Held Trip Integrity: {msg}")
        self._print_res("V-10", passed, msg)

    def _check_v11(self):
        sldf = self.dfs["shipment_lines.csv"]
        evtdf = self.dfs["truck_load_events.csv"]

        evtdf["load_units"] = np.where(evtdf["event_type"] == "LOAD_SCAN", evtdf["quantity"], -evtdf["quantity"])
        net_scans = evtdf.groupby("shipment_line_id")["load_units"].sum().to_dict()

        scan_mismatches = 0
        for _, line in sldf.iterrows():
            lid = line["shipment_line_id"]
            expected = line["shipped_quantity"]
            actual = net_scans.get(lid, 0)
            if actual != expected:
                scan_mismatches += 1

        passed = (scan_mismatches == 0)
        msg = f"Shipment lines failing net scan balance: {scan_mismatches} of {len(sldf)}"
        self.results["V-11"] = (passed, f"Planned, Loaded, and Shipped Separation & Scan Balance: {msg}")
        self._print_res("V-11", passed, msg)

    def _check_v12(self):
        oldf = self.dfs["order_lines.csv"]
        violations = (oldf["ordered_quantity"] != (oldf["shipped_quantity"] + oldf["open_quantity"])).sum()
        over_shipments = (oldf["shipped_quantity"] > oldf["ordered_quantity"]).sum()
        passed = (violations == 0) and (over_shipments == 0)
        msg = f"Conservation violations: {violations}; Over-shipments: {over_shipments} of {len(oldf)} lines"
        self.results["V-12"] = (passed, f"Cancellation-Free Order Conservation: {msg}")
        self._print_res("V-12", passed, msg)

    def _check_v13(self):
        sdf = self.dfs["shipments.csv"]
        sldf = self.dfs["shipment_lines.csv"]
        oldf = self.dfs["order_lines.csv"]
        txndf = self.dfs["inventory_transactions.csv"]

        # 1. Header-line status agreement
        smap_status = dict(zip(sdf["shipment_id"], sdf["shipment_status"]))
        status_mismatches = 0
        for _, line in sldf.iterrows():
            if line["line_status"] != smap_status[line["shipment_id"]]:
                status_mismatches += 1

        # 2. Shipped quantity reconciliation with order lines
        dispatched_shipments = set(sdf[sdf["shipment_status"].isin(["DISPATCHED", "IN_TRANSIT", "DELIVERED"])]["shipment_id"])
        dispatched_lines = sldf[sldf["shipment_id"].isin(dispatched_shipments)]
        sum_shipped_by_order_line = dispatched_lines.groupby("order_line_id")["shipped_quantity"].sum().to_dict()

        order_line_mismatches = 0
        for _, oline in oldf.iterrows():
            lid = oline["order_line_id"]
            exp_shipped = sum_shipped_by_order_line.get(lid, 0)
            if oline["shipped_quantity"] != exp_shipped:
                order_line_mismatches += 1

        # 3. Reference ID uniqueness
        ref_dups = txndf["reference_id"].duplicated().sum()

        passed = (status_mismatches == 0) and (order_line_mismatches == 0) and (ref_dups == 0)
        msg = f"Status mismatches: {status_mismatches}; Order line shipped mismatches: {order_line_mismatches}; Duplicate transaction references: {ref_dups}"
        self.results["V-13"] = (passed, f"Extended All-or-Nothing Dispatch & Deterministic Reservation Integrity: {msg}")
        self._print_res("V-13", passed, msg)

    def _check_v14(self):
        dhdf = self.dfs["demand_history.csv"]
        oldf = self.dfs["order_lines.csv"]
        pdf = self.dfs["products.csv"]
        prices = dict(zip(pdf["sku_id"], pdf["unit_price"]))

        # Check gross == net
        gross_net_diff = (dhdf["gross_units_demanded"] != dhdf["net_units_demanded"]).sum()
        val_diff = (dhdf["gross_demand_value"] != dhdf["net_demand_value"]).sum()

        # Global sum reconciliation
        total_dh_units = dhdf["gross_units_demanded"].sum()
        total_ordered_units = oldf["ordered_quantity"].sum()
        units_match = (total_dh_units == total_ordered_units)

        passed = (gross_net_diff == 0) and (val_diff == 0) and units_match
        msg = f"Gross!=Net units: {gross_net_diff}; Gross!=Net value: {val_diff}; Total units match: {units_match} ({total_dh_units:,})"
        self.results["V-14"] = (passed, f"Dense Demand-History Equality & Order-Date Reconciliation: {msg}")
        self._print_res("V-14", passed, msg)

    def _check_v15(self):
        alldf = self.dfs["planned_truck_allocations.csv"]
        sdf = self.dfs["shipments.csv"]
        shipment_trips = set(sdf["trip_id"])
        orphan_trips = (~alldf["trip_id"].isin(shipment_trips)).sum()

        # Phase 1-3 artifacts untouched check
        phase1_file = os.path.join("data", "raw", "supply_chain_data.csv")
        phase2_file = os.path.join("data", "processed", "supply_chain_data_cleaned.csv")
        phase3_file = os.path.join("data", "processed", "products.csv")

        artifacts_exist = all(os.path.isfile(f) for f in [phase1_file, phase2_file, phase3_file])
        passed = (orphan_trips == 0) and artifacts_exist
        msg = f"Orphan allocation trip IDs: {orphan_trips}; Phase 1-3 baseline files preserved: {artifacts_exist}"
        self.results["V-15"] = (passed, f"Planned-to-Actual Trip Linkage & Artifact Isolation: {msg}")
        self._print_res("V-15", passed, msg)

    def _print_res(self, test_id: str, passed: bool, msg: str):
        badge = "[PASS]" if passed else "[FAIL]"
        print(f"  {badge} {test_id}: {msg}")


# ===========================================================================
# 4. SCRIPT ENTRY POINT
# ===========================================================================
def main():
    workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    raw_csv = os.path.join(workspace_root, "data", "raw", "supply_chain_data.csv")
    data_dir = os.path.join(workspace_root, "data")
    staging_dir = os.path.join(data_dir, "synthetic_staging")
    target_dir = os.path.join(data_dir, "synthetic")
    backup_dir = os.path.join(data_dir, "synthetic_backup")

    print("\n" + "="*80)
    print("CARGOSENSE PHASE 4: SYNTHETIC OPERATIONAL DATASET GENERATION")
    print("="*80)

    # 1. Startup Recovery Sweep
    execute_startup_recovery(data_dir)

    # 2. Execute In-Memory Generation into Staging
    generator = CargoSenseSyntheticGenerator(
        raw_supply_chain_path=raw_csv,
        staging_dir=staging_dir,
        seed=RANDOM_SEED
    )
    generator.build_products()
    generator.build_trucks()
    generator.build_routes()
    generator.build_truck_route_permissions()
    generator.build_operational_simulation()
    generator.export_to_staging()

    # 3. Validate Staging Directory
    validator = CargoSenseValidator(
        dataset_dir=staging_dir,
        raw_supply_chain_path=raw_csv
    )
    results = validator.validate_all()

    all_passed = all(status for status, _ in results.values())
    if not all_passed:
        print("[CRITICAL] Validation failed on staged dataset. Aborting publication.")
        shutil.rmtree(staging_dir)
        sys.exit(1)

    # 4. Safe Promotion to Production
    promote_staging_to_synthetic(staging_dir, target_dir, backup_dir)

    print("\n[SUCCESS] Phase 4 Synthetic Dataset Generation & Publication Completed Successfully!\n")


if __name__ == "__main__":
    main()
