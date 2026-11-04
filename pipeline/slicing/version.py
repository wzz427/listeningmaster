"""引擎版本：全仓唯一出处，timeline.json 的 engine 字段从这读（SPEC-012 R4）。

改了切割行为才动小版本号；纯搬家、接线不动。动版本号＝金样考卷要跟着重刷（tests/test_slicing.py）。
1.1.0（2026-11-04）：无讲稿路（SPEC-013）——识别删掉帮倒忙的 speaker_count；没讲稿的材料
拼词、巨词加空格、标点并半句、编号归并起名一条新链；带讲稿路一行没动（四课金样重放逐句一致）。
1.0.1（2026-11-03）：讲稿断行断在缩略词中间时拼回去当一个词（o'＋clock. → o'clock.，260821 第 48 句）。
"""

VERSION = "1.1.0"
ENGINE_VERSION = f"slicing/{VERSION}"
