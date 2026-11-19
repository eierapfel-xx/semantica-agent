"""備考の条文の解析と照合（仕様 §5.4 の検証用。決定的に動く）。"""

import re
import unicodedata
from dataclasses import replace

from semantica_agent.core.ids import ProvisionRef
from semantica_agent.core.vocab import LAW_ALIASES, LAW_SLUGS

_LAW_NAMES = sorted([*LAW_SLUGS, *LAW_ALIASES], key=len, reverse=True)
_TOKEN = re.compile(
    "(?P<law>" + "|".join(re.escape(n) for n in _LAW_NAMES) + ")"
    r"|(?P<appendix>附録第\d+号)"
    r"|第?(?P<art>\d+)条(?:の(?P<branch>\d+)|(?P<typo>\d+)(?=第))?"
    r"|第?(?P<para>\d+)項(?:[～〜~]第?(?P<para_to>\d+)項)?"
    r"|第(?P<item>\d+)号"
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("~", "～")


class _State:
    def __init__(self) -> None:
        self.law: str | None = None
        self.article: ProvisionRef | None = None
        self.emitted = False
        self.out: list[ProvisionRef] = []

    def flush(self) -> None:
        if self.article and not self.emitted:
            self.out.append(self.article)
        self.article = None
        self.emitted = False

    def emit(self, ref: ProvisionRef) -> None:
        self.out.append(ref)
        self.emitted = True


def parse_provisions(text: str) -> list[ProvisionRef]:
    st = _State()
    for m in _TOKEN.finditer(normalize(text)):
        g = m.groupdict()
        if g["law"]:
            st.flush()
            st.law = LAW_ALIASES.get(g["law"], g["law"])
        elif g["appendix"]:
            continue
        elif g["art"] and st.law:
            st.flush()
            branch = g["branch"] or g["typo"]
            st.article = ProvisionRef(st.law, int(g["art"]), int(branch) if branch else None)
        elif g["para"] and st.article:
            last = int(g["para_to"] or g["para"])
            for p in range(int(g["para"]), last + 1):
                st.emit(replace(st.article, paragraph=p))
        elif g["item"] and st.article:
            if st.emitted and st.out[-1].item is None and st.out[-1].paragraph is not None:
                st.out[-1] = replace(st.out[-1], item=int(g["item"]))
            else:
                st.emit(replace(st.article, item=int(g["item"])))
    st.flush()
    return st.out


def provision_appears_in(ref: ProvisionRef, remarks: str) -> bool:
    parsed = parse_provisions(remarks)
    if ref in parsed:
        return True
    if ref.paragraph is None and ref.item is None:
        return any(
            (p.law, p.article, p.branch) == (ref.law, ref.article, ref.branch) for p in parsed
        )
    return False
