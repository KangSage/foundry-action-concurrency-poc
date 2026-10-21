# Foundry Python transforms. 경로·이름 빈칸은 내부 AI가 채운다.
from datetime import datetime, timezone

from transforms.api import Input, Output, incremental, transform, transform_df

from . import revision_logic as R  # 레포 구조에 맞게 import 경로 수정

ROOT = "{{우리 Foundry Project}}"
CODE = "{{원천코드}}"


# 이력이 사라지지 않게 require_incremental=True. semantic_version 은 절대 올리지 않는다.
@incremental(snapshot_inputs=["master", "mirror"], require_incremental=True, semantic_version=1)
@transform(
    revision=Output(ROOT + "/revision/" + CODE + "_REVISION"),
    receipt=Output(ROOT + "/revision/" + CODE + "_RECEIPT"),
    master=Input(ROOT + "/master/" + CODE + "_master"),
    mirror=Input(ROOT + "/raw/" + CODE + "_mirror"),
)
def compute_revision(master, mirror, revision, receipt):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    receipt_id = R.SRC_SYSTEM + "_" + now.strftime("%Y%m%dT%H%M%S")

    m = master.dataframe()
    mir = mirror.dataframe()
    prev = revision.dataframe("previous", schema=R.revision_schema(m.schema))

    new = R.compute_revisions(m, mir, prev, receipt_id, now)
    revision.write_dataframe(new)  # incremental: 추가 (APPEND)
    receipt.write_dataframe(R.compute_receipt(new, m, mir, receipt_id, now))


@transform_df(
    Output(ROOT + "/revision/" + CODE + "_HEAD"),
    revision=Input(ROOT + "/revision/" + CODE + "_REVISION"),
)
def compute_head(revision):
    return R.compute_head(revision)  # 매번 전체 다시 계산 (SNAPSHOT)
