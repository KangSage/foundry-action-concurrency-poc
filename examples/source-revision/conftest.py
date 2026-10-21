# 로컬 실행용. Foundry Code Repository 에는 spark_session fixture 가 이미 있으므로 이 파일은 넣지 않는다.
import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark_session():
    spark = SparkSession.builder.master("local[1]").config("spark.ui.enabled", "false").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    yield spark
    spark.stop()
