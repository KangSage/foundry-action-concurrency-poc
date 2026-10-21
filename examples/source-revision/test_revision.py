import revision_logic as R

KW = dict(key="k", compare_cols=["a", "b"], keep_cols=["k", "a", "b"], src_system="SYN")

def run(spark, master_rows, mirror_keys, prev, rid, ts):
    m = spark.createDataFrame(master_rows, "k string, a string, b string")
    mir = spark.createDataFrame([(x,) for x in mirror_keys], "k string")
    new = R.compute_revisions(m, mir, prev, rid, ts, **KW)
    assert [f.name for f in new.schema.fields] == [f.name for f in prev.schema.fields]
    rc = R.compute_receipt(new, m, mir, rid, ts, src_system="SYN")
    return prev.unionByName(new), new, rc

def show(new):
    return sorted((r.k, r.src_rev_no, r.change_type, r.a) for r in new.collect())

def test_revision_flow(spark_session):
    spark = spark_session
    master_schema = spark.createDataFrame([], "k string, a string, b string").schema
    rev_schema = R.revision_schema(master_schema, key="k", keep_cols=["k", "a", "b"])
    prev = spark.createDataFrame([], rev_schema)
    # 1회차: 2행 새로
    prev, new, rc = run(spark, [("1", "x", "p"), ("2", "y", "q")], ["1", "2", "3"], prev, "r1", "2026-10-21 00:00:00")
    assert show(new) == [("1", 0, "INSERT", "x"), ("2", 0, "INSERT", "y")], show(new)
    # 2회차: 변경 없음 (공백만 다름 → 정규화로 같음)
    prev, new, rc = run(spark, [("1", "x ", "p"), ("2", "y", "q")], ["1", "2", "3"], prev, "r2", "2026-10-21 01:00:00")
    assert show(new) == [], show(new)
    assert rc.collect()[0].insert_count == 0
    # 3회차: 1 바뀜, 2 필터 밖(복사본엔 있음), 3 새로
    prev, new, rc = run(spark, [("1", "x2", "p"), ("3", "z", None)], ["1", "2", "3"], prev, "r3", "2026-10-21 02:00:00")
    assert show(new) == [("1", 1, "UPDATE", "x2"), ("2", 1, "OUT_OF_SCOPE", "y"), ("3", 0, "INSERT", "z")], show(new)
    # 4회차: 3 원천 삭제, 2 다시 들어옴
    prev, new, rc = run(spark, [("1", "x2", "p"), ("2", "y", "q")], ["1", "2"], prev, "r4", "2026-10-21 03:00:00")
    assert show(new) == [("2", 2, "REINSERT", "y"), ("3", 1, "DELETE", "z")], show(new)
    r = rc.collect()[0]
    assert (r.reinsert_count, r.delete_count, r.mirror_row_count, r.master_row_count) == (1, 1, 2, 2), r
    # 5회차: 삭제된 3은 계속 없음 → 새 행 없음
    prev, new, rc = run(spark, [("1", "x2", "p"), ("2", "y", "q")], ["1", "2"], prev, "r5", "2026-10-21 04:00:00")
    assert show(new) == [], show(new)
    # null 값 비교: b None -> "" 는 다른 값
    prev, new, rc = run(spark, [("1", "x2", "p"), ("2", "y", "")], ["1", "2"], prev, "r6", "2026-10-21 05:00:00")
    assert show(new) == [("2", 3, "UPDATE", "y")], show(new)
    head = R.compute_head(prev, key="k")
    assert sorted((r.k, r.src_rev_no, r.change_type) for r in head.collect()) == [("1", 1, "UPDATE"), ("2", 3, "UPDATE"), ("3", 1, "DELETE")]
    pks = [r.revision_pk for r in prev.collect()]
    assert len(pks) == len(set(pks)) and "SYN_2_3" in pks
