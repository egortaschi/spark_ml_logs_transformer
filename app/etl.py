from functools import lru_cache
from pathlib import Path
from pyspark.sql import Row
from pyspark.sql.functions import col, unix_timestamp, expr, to_timestamp, min, max

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType,
    BooleanType,
    FloatType,
)


def get_spark(master="local[1]", app_name="ML Logs Transformer"):
    """
    Initialize and return a Spark session.

    Parameters:
    master (str): The master URL for the cluster (e.g., "local[1]" for local mode with one thread).
    app_name (str): The name of the Spark application.

    Returns:
    SparkSession: The initialized Spark session.
    """
    try:
        spark = SparkSession.builder \
            .master(master) \
            .appName(app_name) \
            .getOrCreate()
        return spark
    except Exception as e:
        print(f"Error initializing Spark session: {e}")
        raise


def load_logs(logs_path: Path) -> DataFrame:
    """
    Load logs from a given JSON file path and return a Spark DataFrame.

    This function reads a JSON file containing log data and converts it into a Spark DataFrame with a predefined schema.
    The schema includes the following fields:
        - logId: StringType
        - expId: IntegerType
        - metricId: IntegerType
        - valid: BooleanType
        - createdAt: StringType
        - ingestedAt: StringType
        - step: IntegerType
        - value: FloatType

    Args:
        logs_path (Path): The path to the JSON file containing the logs.

    Returns:
        DataFrame: A Spark DataFrame containing the logs data.
    """
    schema = StructType(
        [
            StructField("logId", StringType()),
            StructField("expId", IntegerType()),
            StructField("metricId", IntegerType()),
            StructField("valid", BooleanType()),
            StructField("createdAt", StringType()),
            StructField("ingestedAt", StringType()),
            StructField("step", IntegerType()),
            StructField("value", FloatType()),
        ]
    )
    logs_df = get_spark().read.json(str(logs_path), schema=schema)

    return logs_df


def load_experiments(experiments_path: Path) -> DataFrame:
    """
        Load experiments from a given CSV file path and return a Spark DataFrame.

        This function reads a CSV file containing experiment data and converts it into a Spark DataFrame
        with a predefined schema.
        The schema includes the following fields:
            - expId: IntegerType
            - expName: StringType

        Args:
            experiments_path (Path): The path to the CSV file containing the experiments.

        Returns:
            DataFrame: A Spark DataFrame containing the experiments data.
        """
    schema = StructType([StructField("expId", IntegerType()),
                         StructField("expName", StringType())])
    experiments_df = get_spark().read.csv(str(experiments_path), schema=schema, header=True)

    return experiments_df


def load_metrics() -> DataFrame:
    """
        Load a dummy dataset of metrics and return a Spark DataFrame.

        This function creates a dummy dataset with predefined metric IDs and names,
        then converts it into a Spark DataFrame with a predefined schema.
        The schema includes the following fields:
            - metricId: IntegerType
            - metricName: StringType

        Returns:
            DataFrame: A Spark DataFrame containing the dummy metrics data.
        """
    schema = StructType([StructField("metricId", IntegerType()),
                         StructField("metricName", StringType())])

    metrics = [Row(metricId=0, metricName="Loss"),
               Row(metricId=1, metricName="Accuracy")]

    metrics_df = get_spark().createDataFrame(metrics, schema=schema)

    return metrics_df


def join_tables(logs: DataFrame, experiments: DataFrame, metrics: DataFrame) -> DataFrame:
    """
        Join logs, experiments and metrics DataFrames into a single DataFrame.

        This function performs the following joins:
            1. Join logs with experiments on expId.
            2. Join the result with metrics on metricId.

        Args:
            logs (DataFrame): The logs DataFrame.
            experiments (DataFrame): The experiments DataFrame.
            metrics (DataFrame): The metrics DataFrame.
    """
    # Join logs with experiments on expId
    logs_experiments = logs.join(experiments, on="expId", how="inner")

    # Add metrics to logs_experiments df (join on metricId)
    joined_tables = logs_experiments.join(metrics, on="metricId", how="inner")

    joined_tables = joined_tables.select(
                "logId",
                "expId",
                "expName",
                "metricId",
                "metricName",
                "valid",
                "createdAt",
                "ingestedAt",
                "step",
                "value"
                )

    return joined_tables


def filter_late_logs(data: DataFrame, hours: int) -> DataFrame:
    """
        Filter logs where the difference between 'createdAt' and 'ingestedAt' is greater than a specified number of hours.

        Args:
            data (DataFrame): The DataFrame containing the joined logs, experiments, and metrics.
            hours (int): The threshold in hours to filter late logs.

        Returns:
            DataFrame: A DataFrame containing only the logs where the time difference is greater than the specified hours.
        """
    # Convert the timestamp strings to timestamp type
    data = data.withColumn("created_at_ts", to_timestamp(col("createdAt"), "yyyy-MM-dd'T'HH:mm:ss"))
    data = data.withColumn("ingested_at_ts", to_timestamp(col("ingestedAt"), "yyyy-MM-dd'T'HH:mm:ss"))

    # Calculate the time difference in hours
    time_diff_col = (unix_timestamp(col("ingested_at_ts")) - unix_timestamp(col("created_at_ts"))) / 3600

    # Add the time difference column to the DataFrame
    data_with_time_diff = data.withColumn("time_diff_hours",time_diff_col)

    # Filter the DataFrame
    filtered_logs = data_with_time_diff.filter(col("time_diff_hours") > hours)

    return filtered_logs
    

def calculate_experiment_final_scores(data: DataFrame) -> DataFrame:
    """
    Calculate the final scores for each experiment and metric.

    This function calculates the minimum and maximum values for each metric in each experiment.
    The resulting DataFrame includes the following columns:
        - expName: name of the experiment,
        - metricName: name of the metric,
        - maxValue: maximum value of the metric in the experiment,
        - minValue: minimum value of the metric in the experiment.

    Args:
        data (DataFrame): The DataFrame containing the filtered logs with experiment and metric information.

    Returns:
        DataFrame: A DataFrame containing the final scores for each experiment and metric.
    """
    scores = data.groupBy("expId", "metricId").agg(max("value").alias("maxValue"), min("value").alias("minValue"))

    return scores


def save(data: DataFrame, output_path: Path) -> None:
    """
    Save the DataFrame to Parquet format partitioned by metricId.

    Args:
        data (DataFrame): The DataFrame containing the final scores.
        output_path (str): The output path where the Parquet files will be saved.

    """
    data.write.partitionBy("metricId").parquet(str(output_path))

