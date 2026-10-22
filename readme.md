# CargoSense — AI-Powered Smart Logistics Optimization

## Project Overview

CargoSense is an AI-powered logistics optimization project designed to identify **Partially Loaded Trucks (PTL)** and recommend suitable SKU combinations to improve truck utilization. It combines demand analysis, inventory availability, route compatibility, and predictive modeling to support better truck-loading and dispatch decisions.

## Datasets

1. **Dataset 1 — Supply Chain Dataset:** [https://www.kaggle.com/datasets/amirmotefaker/supply-chain-dataset]
2. **Dataset 2 — Smart Logistics Dataset:** [https://www.kaggle.com/datasets/ziya07/smart-logistics-supply-chain-dataset]

## Project Pipeline

**Source Datasets → Data Cleaning → Product Preparation → Logistics Data by schemas → Ode dataset and pportunity Detection → Opportunity Analysis → Predictive Modeling → Optimization and Recommendations**

## Phase-wise Summary

### Phase 1 — Project Setup and Problem Understanding
Defined the logistics optimization problem, project objectives, and the PTL-to-FTL conversion approach. Established the overall workflow for identifying and evaluating truck-loading opportunities.

### Phase 2 — Data Cleaning and EDA
Cleaned the source datasets, handled missing values and inconsistencies, and performed exploratory data analysis. Prepared structured datasets for subsequent processing.

### Phase 3 — Product Dataset Preparation
Prepared the product catalog by assigning physical attributes and warehouse information. Organized product data to support inventory, capacity, and compatibility calculations.

### Phase 4 — Operational Dataset schemas separated by entities
Created a logistics ecosystem containing products, trucks, routes, orders, shipments, inventory, planning snapshots, and demand history. Validated and analyzed the generated CSV tables to check their consistency and understand the simulated operations.

### Phase 5 — EDA on phase 4. Merged


### Phase 6 — Opportunity Detection Engine (ODE) Dataset
Built the opportunity dataset by identifying partially loaded truck shipments and generating feasible candidate SKU combinations. Simulated operational outcomes to create the `Became_FTL` target label for later predictive modeling.

### Phase 7 — Demand, Inventory and Opportunity Analysis
Analyzed the generated opportunities using demand, inventory, truck utilization, and candidate SKU features. Compared opportunities that became FTL with those that did not and shortlisted features for baseline machine-learning models.

### Phase 8 — Feature engineering for baseline models
Feature engineering for baseline models. 

### Phase 9 — ML Models Training
Train shortlisted ML models and record 4 sets of results.

## Work Distribution

```
Team A: Saloni + Vaidehi
Team B: Sameera + Sanchita

Dataset hopping order (FOLDERS) : raw->schemas>processed

Work Timeline:
[ALL] Find raw datasets of products, inventory, trucks and dispatches - kaggle
[TEAM-A] Clean them and process them
[TEAM-A] Do eda on them and make final products.csv and nb3.
[TEAM-B] Also do same and make nb4 and then make file simulated_operational_events.csv

Now have to build ode dataset like what all ode uses. But this is not for models btw. A more refined version of this for models later. 

[TEAM-B] Ode dataset made from various csvs from 3. And 4. And the helper. 
[TEAM-B] Now do nb-7 eda on ode dataset - to check potential for feature eng for phase 8. If not good potential then work on dataset of ode more. If yes then hand off for phase 8. It was handed off.
[TEAM-A] Phase 8- feature engineering - feature extraction, custom features etc and shortlisting for baseline models.
[TEAM-B] Train Model M1 - to be done 
[TEAM-A] Train Model M2  - to be done

Team A+B= Work Number 1 : cause its easy just dataset searching
Team A: Work Number 2,3,7
Team B: Work Number 4,5,6


Files made :

Team A:
Dataset files: supply_chain_data_cleaned.csv , smart_logistics_dataset_cleaned.csv, products.csv, 

Notebooks and Files:
notebooks/ phase 3,8
src->phase1,2,phase3,phase8 , phase 4 together

Team: B 
Dataset files: simulated_operational_events.csv , ode_opportunities.csv 

Notebooks and Files:
notebooks/phase 4,7
src->phase 6,7 , phase 4 together

Team A+B: 
All 14 csvs of schemas folder. They were helper scvs made to preserve original structure and schema of all entities. 

```


