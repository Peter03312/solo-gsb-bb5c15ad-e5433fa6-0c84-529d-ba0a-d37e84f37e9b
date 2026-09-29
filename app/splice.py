"""按选区列表从现有 cue 时间轴剪取并拼接新时间轴的纯逻辑层。

选区列表的顺序即拼接顺序（可乱序、相互重叠或重复）：每个选区
``[sel.start, sel.end)`` 贡献固定时长 ``sel.end - sel.start``，因此选区
``i`` 之前全部选区时长之和就是该选区片段在新时间轴上的偏移；选区中的
空白（源时间轴上与任何 cue 都不相交的部分，含超出源时间轴的部分）同样
计入总时长。

每条源 cue 只取与选区**严格相交**（交集时长 > 0，仅端点相接不算）的部分：

* 交集起点相对选区起点的时间为 ``max(cue.start, sel.start) - sel.start``；
* 跨选区边界的 cue 在边界处裁断；
* 同一源 cue 被多个选区选中时，每个选区各生成一个片段，id 互不相同，
  并保留原 id 与选区序号。
"""

from __future__ import annotations

from .models import Cue, Selection, SpliceCue


def splice_cues(cues: list[Cue], selections: list[Selection]) -> tuple[list[SpliceCue], float]:
    """按 selections 的顺序从 cues 剪取并拼接。

    返回 (拼接后的 cue 列表, 总时长)。
    片段按选区顺序排列；同一选区内的片段按源时间顺序（即交集起点）排列。
    空 selections 返回 ([], 0.0)。
    调用前请求模型已保证选区端点非负、end > start，且源 cue id 唯一、
    源时间轴不存在严格重叠。
    """
    result: list[SpliceCue] = []
    offset = 0.0

    # 源时间轴无重叠，按开始时间排序后，选区内片段自然按源时间顺序产出
    ordered_cues = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.id))

    for sel_idx, sel in enumerate(selections):
        for cue in ordered_cues:
            intersect_start = max(cue.start, sel.start)
            intersect_end = min(cue.end, sel.end)
            if intersect_end <= intersect_start:
                # 不相交或仅端点相接：严格相交才剪取
                continue
            result.append(
                SpliceCue(
                    id=f"{cue.id}#{sel_idx}",
                    source_id=cue.id,
                    selection=sel_idx,
                    start=offset + intersect_start - sel.start,
                    end=offset + intersect_end - sel.start,
                    text=cue.text,
                    speaker=cue.speaker,
                )
            )
        offset += sel.end - sel.start

    return result, offset
