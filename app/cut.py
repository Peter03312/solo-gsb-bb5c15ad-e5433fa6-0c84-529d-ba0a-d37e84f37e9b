"""按选区列表从现有 cue 时间轴剪取字幕并顺序拼接的纯逻辑层。

给定源时间轴（cues）与一组按顺序排列的选区（selections，闭开风格的
时间区间 ``[start, end)``），把每个选区与源 cue **严格相交**（交集时长
大于 0，仅端点相接不算）的部分依次裁出，按选区在列表中的顺序首尾相接地
拼成一条新时间轴。选区允许乱序、重叠或重复，处理顺序严格以请求列表为准。

新时间计算（以第 i 个选区为例，i 从 1 开始）：

* 此前所有选区的时长之和记作 ``offset``——选区中没有命中任何 cue 的空白
  时段同样计入总时长，因此空白会表现为输出 cue 之间的时间空隙；
* cue 与选区的交集为 ``[lo, hi)``，其相对选区起点的位置为
  ``lo - selection.start``，故输出区间为
  ``[offset + lo - sel.start, offset + hi - sel.start)``；
* 处理完该选区后 ``offset += selection.end - selection.start``。

跨选区边界的 cue 在边界处裁断；同一源 cue 被多个选区（或同一选区重复
出现）多次命中时，每次各自生成一条新 cue，id 为
``"{源id}#s{选区序号}"``，并保留 ``source_id`` 与 1 基的 ``selection``。
文本与说话人原样保留，不做逐字切分。

源时间轴存在重复 cue id 或区间重叠（严格相交，首尾相接不算）即视为
参数错误：收集全部问题后统一返回，不输出任何部分结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .merge import find_overlaps
from .models import Cue, Overlap, Selection, SplicedCue


@dataclass
class CutResult:
    """cut_timeline 的结果。

    duplicate_ids / overlaps 任一非空即参数错误，
    此时 cues 为空、duration 为 0，不输出部分结果。
    """

    cues: list[SplicedCue] = field(default_factory=list)
    duration: float = 0.0
    duplicate_ids: list[str] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)


def cut_timeline(cues: list[Cue], selections: list[Selection]) -> CutResult:
    """按选区顺序从 cues 裁取交集并拼接为新时间轴。

    输出 cue 按 (start, end, source_id) 升序排列；duration 为全部选区
    时长之和（空白计入），与是否命中 cue 无关。
    源 cue id 重复或源时间轴重叠时返回参数错误，不输出部分结果。
    """
    # —— 参数校验：重复 id 与时间轴重叠全部收集，统一报错 ——
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for cue in cues:
        if cue.id in seen_ids:
            duplicate_ids.add(cue.id)
        seen_ids.add(cue.id)

    overlaps = find_overlaps(cues)
    if duplicate_ids or overlaps:
        return CutResult(
            cues=[],
            duration=0.0,
            duplicate_ids=sorted(duplicate_ids),
            overlaps=overlaps,
        )

    # 按源开始时间稳定遍历，使同一选区内部的输出顺序确定（与输入顺序无关）
    ordered_cues = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.id))

    spliced: list[SplicedCue] = []
    offset = 0.0
    for index, selection in enumerate(selections, start=1):
        for cue in ordered_cues:
            lo = max(cue.start, selection.start)
            hi = min(cue.end, selection.end)
            if hi > lo:  # 严格相交：仅端点相接（hi == lo）不产出
                spliced.append(
                    SplicedCue(
                        id=f"{cue.id}#s{index}",
                        start=offset + (lo - selection.start),
                        end=offset + (hi - selection.start),
                        text=cue.text,
                        speaker=cue.speaker,
                        source_id=cue.id,
                        selection=index,
                    )
                )
        # 选区中的空白同样计入总时长
        offset += selection.end - selection.start

    spliced.sort(key=lambda cue: (cue.start, cue.end, cue.source_id))
    return CutResult(cues=spliced, duration=offset)
