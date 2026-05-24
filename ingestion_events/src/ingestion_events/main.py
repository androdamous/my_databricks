import argparse
from databricks.sdk.runtime import spark
from pyspark.sql import types as T

import pandas as pd
import numpy as np

def generate_random_uid_df():
    uid = int(np.random.randint(0, 1000000) * 2 - np.random.randint(0, 1000))
    
    df = pd.DataFrame(
        {
            "uid": [uid]
        }
    )

    return df

def main():
    # Process command-line arguments
    parser = argparse.ArgumentParser(
        description="Databricks job with catalog and schema parameters",
    )

    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()

    catalog = args.catalog
    schema = args.schema

    schema_struct = T.StructType([
        T.StructField("uid", T.IntegerType(), True),
    ])

    dff = spark.createDataFrame(
        generate_random_uid_df(),
        schema_struct
    )

    dff.write.format("delta").mode("append").saveAsTable(f"{catalog}.{schema}.ingestion_events")

    return


if __name__ == "__main__":
    main()
