from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

# 설정 (내부 AI가 채움)
SRC_SYSTEM = "{{원천코드}}"
KEY = "{{원천 키 컬럼}}"
COMPARE_COLS = ["{{비교 컬럼 1}}", "{{비교 컬럼 2}}"]   # 순서 고정. 바꾸면 전체가 새 리비전
KEEP_COLS = ["{{보관 컬럼 1}}", "{{보관 컬럼 2}}"]      # COMPARE_COLS 포함

GONE = ["DELETE", "OUT_OF_SCOPE"]


def row_hash(cols):
    # 정규화: 문자열로 바꾸고 앞뒤 공백 제거, null 은 고정 기호
    parts = [F.coalesce(F.trim(F.col(c).cast("string")), F.lit("␀")) for c in cols]
    return F.sha2(F.concat_ws("\u001f", *parts), 256)


def compute_revisions(master, mirror, previous, receipt_id, captured_at,
                      key=KEY, compare_cols=COMPARE_COLS, keep_cols=KEEP_COLS,
                      src_system=SRC_SYSTEM):
    """이번 실행에서 새로 쌓을 REVISION 행만 돌려준다."""
    cur = (master.select(key, *[c for c in keep_cols if c != key])
           .withColumn("row_hash", row_hash(compare_cols)))

    w = Window.partitionBy(key).orderBy(F.col("src_rev_no").desc())
    last = (previous.withColumn("_rn", F.row_number().over(w))
            .filter("_rn = 1").drop("_rn"))

    in_mirror = mirror.select(key).distinct().withColumn("_in_mirror", F.lit(True))

    c = cur.alias("c")
    l = last.alias("l")
    j = (c.join(l, F.col(f"c.{key}") == F.col(f"l.{key}"), "full_outer")
         .withColumn("_key", F.coalesce(F.col(f"c.{key}"), F.col(f"l.{key}"))))
    j = j.join(in_mirror.withColumnRenamed(key, "_key"), "_key", "left")

    cur_present = F.col("c.row_hash").isNotNull()
    last_present = F.col("l.src_rev_no").isNotNull()
    last_gone = F.col("l.change_type").isin(GONE)

    change = (F.when(cur_present & ~last_present, "INSERT")
              .when(cur_present & last_gone, "REINSERT")
              .when(cur_present & (F.col("c.row_hash") != F.col("l.row_hash")), "UPDATE")
              .when(~cur_present & last_present & ~last_gone,
                    F.when(F.col("_in_mirror"), "OUT_OF_SCOPE").otherwise("DELETE")))

    rev_no = F.when(~last_present, F.lit(0)).otherwise(F.col("l.src_rev_no") + 1)
    # 사라진 행은 마지막 값 유지
    take = lambda name: F.when(cur_present, F.col(f"c.{name}")).otherwise(F.col(f"l.{name}"))

    out = (j.withColumn("change_type", change)
           .filter(F.col("change_type").isNotNull())
           .select(
               F.lit(src_system).alias("src_system"),
               F.col("_key").alias(key),
               rev_no.cast("int").alias("src_rev_no"),
               F.col("change_type"),
               take("row_hash").alias("row_hash"),
               F.lit(receipt_id).alias("receipt_id"),
               F.lit(captured_at).cast("timestamp").alias("captured_at"),
               *[take(k).alias(k) for k in keep_cols if k != key],
           ))
    return out.withColumn(
        "revision_pk",
        F.concat_ws("_", F.col("src_system"), F.col(key).cast("string"),
                    F.col("src_rev_no").cast("string")))


def revision_schema(master_schema, key=KEY, keep_cols=KEEP_COLS):
    """REVISION 출력 스키마. 'previous' 읽기에 필요. compute_revisions 출력 순서와 같다."""
    fields = {f.name: f for f in master_schema.fields}
    return T.StructType([
        T.StructField("src_system", T.StringType()),
        fields[key],
        T.StructField("src_rev_no", T.IntegerType()),
        T.StructField("change_type", T.StringType()),
        T.StructField("row_hash", T.StringType()),
        T.StructField("receipt_id", T.StringType()),
        T.StructField("captured_at", T.TimestampType()),
        *[fields[c] for c in keep_cols if c != key],
        T.StructField("revision_pk", T.StringType()),
    ])


def compute_head(revision, key=KEY):
    w = Window.partitionBy("src_system", key).orderBy(F.col("src_rev_no").desc())
    return (revision.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")
            .withColumn("head_pk", F.concat_ws("_", F.col("src_system"), F.col(key).cast("string"))))


def compute_receipt(new_revisions, master, mirror, receipt_id, received_at, src_system=SRC_SYSTEM):
    counts = {t: F.sum(F.when(F.col("change_type") == t, 1).otherwise(0)).cast("int")
              for t in ["INSERT", "UPDATE", "DELETE", "REINSERT", "OUT_OF_SCOPE"]}
    agg = new_revisions.agg(*[F.coalesce(v, F.lit(0)).alias(f"{k.lower()}_count") for k, v in counts.items()])
    spark = master.sparkSession
    base = spark.createDataFrame([(receipt_id, src_system)], "receipt_id string, src_system string")
    return (base.crossJoin(agg)
            .withColumn("received_at", F.lit(received_at).cast("timestamp"))
            .withColumn("mirror_row_count", F.lit(mirror.count()))
            .withColumn("master_row_count", F.lit(master.count())))
