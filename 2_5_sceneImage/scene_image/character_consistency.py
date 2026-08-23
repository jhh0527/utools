# -*- coding: utf-8 -*-
"""씬별 Face Identity·State Layer 자동 삽입 · 상태키 추적."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_JIN_FACE = (
    "sharp narrow phoenix eyes, high straight nose, thin lips, defined jawline, "
    "youthful East-Asian face with ancient weary eyes, cool fair skin with "
    "porcelain complexion, slender wiry physique, calm unreadable expression"
)

_JIN_ANCHOR = (
    "Always preserve facial identity: same face, sharp narrow phoenix eyes, "
    "high straight nose, thin lips, defined jawline, youthful East-Asian face "
    "with ancient weary eyes, cool fair skin with porcelain complexion, "
    "slender wiry swordsman physique, calm unreadable expression (unless "
    "emotion scene). Hair, robe damage, blood, and wounds must follow the "
    "State Layer only — do not invent random outfit changes. Do not change "
    "facial identity, eye shape, or physique across scenes."
)

_JIN_STATES: dict[str, str] = {
    "base": (
        "jet-black waist-length hair in warrior topknot with jade hairpin, "
        "white Huashan orthodox robes with pale teal accents and flowing layered "
        "sleeves, silver plum-blossom embroidery, dark blue sash, refined "
        "orthodox Huashan jian at waist, no visible wound"
    ),
    "hair_loose": (
        "jet-black waist-length hair partially loosened from topknot, jade "
        "hairpin askew, loose strands over face, same white Huashan pale-teal "
        "robes and sash, refined jian, no wound"
    ),
    "battle_torn": (
        "jet-black waist-length hair in warrior topknot with jade hairpin "
        "(slightly disheveled), white Huashan robes with pale teal torn at "
        "sleeves and hem, silver plum embroidery stained, dark blue sash, "
        "refined jian drawn, light cuts and dust, no deep wound"
    ),
    "blood_robe": (
        "jet-black waist-length hair in warrior topknot with jade hairpin, "
        "white Huashan pale-teal robes with fresh blood spatters on chest and "
        "sleeves, silver plum embroidery, dark blue sash, refined jian, "
        "optional light blood on cheek, no deep wound"
    ),
    "wounded_shoulder": (
        "jet-black waist-length hair in warrior topknot with jade hairpin, "
        "white Huashan pale-teal robes torn at left shoulder with bleeding cut "
        "and blood stain, dark blue sash, refined jian, visible left-shoulder "
        "wound"
    ),
}

_JIN_PAST = (
    "Jin Muhan, approximately thirty-five years old, legendary swordsman under "
    "blood-red rain, tall and gaunt, sharp narrow phoenix eyes, high straight "
    "nose, thin lips, defined jawline, hollow cheeks, cool fair skin with "
    "porcelain complexion turned pale from blood loss, jet-black waist-length "
    "hair soaked with white strands at temples, jade hairpin loosened, deep "
    "bleeding chest wound, torn white Huashan robes with pale teal accents and "
    "silver plum embroidery, broken orthodox Huashan jian used as a walking "
    "staff, tragic grief-stricken expression"
)

_BAEK_FACE = (
    "slightly tanned skin, wolf-like slanted eyes with faint red iris "
    "undertone, thick straight eyebrows, small scar under left ear, "
    "deceptively warm smile, lean athletic build"
)

_BAEK_STATES: dict[str, str] = {
    "base": (
        "dark brown hair in low rough ponytail with leather cord, gray-black "
        "Huashan branch-disciple robes with worn edges and red inner collar "
        "lining, dark cloth forearm wraps, white-hilted jian White Night"
    ),
    "battle_torn": (
        "same face, ponytail disheveled, gray-black robes torn at hem, forearm "
        "wraps frayed, White Night drawn, dust and light cuts, no deep wound"
    ),
    "blood_robe": (
        "same face and ponytail, gray-black robes with blood spatters, red "
        "collar lining visible, White Night, optional jade shard"
    ),
}

_STATIC_LOOKS: dict[str, str] = {
    "Seo": (
        "Seo Ryeongran, approximately seventeen years old, strikingly beautiful "
        "East-Asian young woman of a demon-cult outer branch, pale porcelain "
        "skin, phoenix eyes with faint crimson iris, long straight raven-black "
        "hair to the waist, half-tied with black-and-red silk ribbon, small "
        "vermilion plum-petal mark between brows, slender graceful figure, "
        "crimson-and-black layered silk robes with dark lotus and flame "
        "embroidery, jade belt ornament, slender curved dao with red tassel"
    ),
    "Cheongheo": (
        "Cheongheo Jinin, an elderly Taoist grandmaster in his late 60s, tall "
        "straight-backed, long silver-white hair and beard to the chest, kind "
        "but piercing eyes, weathered serene face, highest-rank Huashan elder "
        "robes deep indigo over white inner layer, silver plum blossom crest, "
        "Taoist eight-trigram jade pendant, horsehair whisk in hand"
    ),
    "Seong": (
        "Seong Yu, approximately nineteen years old, handsome East-Asian noble "
        "youth, bright cheerful features, round warm eyes, neatly combed black "
        "hair in high topknot with golden hairpin, healthy athletic build, "
        "luxurious white-and-gold Huashan orthodox robes, polished longsword "
        "with golden guard"
    ),
    "Namgung": (
        "Namgung Rin, approximately nineteen years old, quiet sharp-eyed "
        "East-Asian youth from a fallen clan branch, tall thin pale complexion, "
        "long narrow cold analytical eyes, dark hair in low ponytail with plain "
        "black cord and a single white mourning ribbon, neat gray branch-disciple "
        "robes, thin straight sword at back"
    ),
    "Wang": (
        "Wang Samdo, a brutal bandit chief in his 40s, muscular thick-necked, "
        "sun-darkened scarred skin, shaved head with wolf scalp tattoo, thick "
        "beard, gold left earring, one milky blind eye and one bloodshot eye, "
        "black leather armor over red inner shirt, wolf-fur cloak, three curved "
        "sabers on body"
    ),
    "Elder": (
        "the White-Haired Elder, mysterious ancient master, extremely long "
        "snow-white hair and beard, face half-hidden in shadow, one visible "
        "pale gray pupil-less eye, layered black robes with faint gold "
        "constellation patterns, optional black jade board with red points"
    ),
    "Mother": (
        "Jin Muhan's mother, a middle-aged East-Asian village woman with gentle "
        "tired eyes and warm smile, simple faded cloth dress and apron, hair "
        "neatly tied with plain pin, humble rural cottage atmosphere"
    ),
}

_DETECT: list[tuple[str, tuple[str, ...]]] = [
    ("Jin", ("진무한", "무한", "진 무한", "Jin Muhan", "Jin Mu-han")),
    ("Baek", ("한백강", "백강", "Han Baekgang", "Baekgang")),
    ("Seo", ("서령란", "령란", "Seo Ryeongran", "Ryeongran")),
    ("Cheongheo", ("청허", "진인", "Cheongheo", "Jinin")),
    ("Seong", ("성유", "Seong Yu", "Seong-Yu")),
    ("Namgung", ("남궁린", "남궁", "Namgung Rin", "Namgung")),
    ("Wang", ("왕삼도", "삼도", "Wang Samdo")),
    ("Elder", ("백발 노인", "백발노인", "판의 주인", "White-Haired Elder")),
    ("Mother", ("어머니", "모친", "Jin Muhan's mother", "진무한의 어머니")),
]

_FLASHBACK_RE = re.compile(
    r"전생|회상|그\s*때|옛날|백\s*년\s*전|서른|삼십\s*오|35\s*세|blood-red rain|"
    r"최후\s*의\s*밤|fallen sword god",
    re.I,
)
_YOUNG_JIN_RE = re.compile(r"열\s*다\s*섯|십\s*오\s*세|15\s*세|입문", re.I)
_SHOULDER_RE = re.compile(r"어깨|shoulder", re.I)
_BLOOD_RE = re.compile(r"피|핏물|선혈|blood", re.I)
_TORN_RE = re.compile(r"찢|찢어|찢긴|torn|tear", re.I)
_HAIR_LOOSE_RE = re.compile(r"풀린|흩어|머리를\s*풀|loosened hair|hair loose", re.I)
_BATTLE_RE = re.compile(r"전투|격斗|싸움|battle|clash|duel", re.I)
_KILLING_RE = re.compile(r"살의|살기| killing intent|restrained killing", re.I)

_STYLE_TAIL = (
    "Chinese wuxia manhua (중국 무협 만화) style illustration, classic Chinese "
    "manhua panel composition, 16:9 aspect ratio, ultra high resolution digital "
    "manhua art, no text, no speech bubbles, no Hangul on image"
)


@dataclass
class CharacterStateTracker:
    """씬 간 상태키 유지 — png 폴더 ``.character_state.json`` 에 저장."""

    states: dict[str, str] = field(default_factory=lambda: {"Jin": "base", "Baek": "base"})
    default_protagonist: str = "Jin"

    @classmethod
    def load(cls, png_dir: Path | str | None = None) -> CharacterStateTracker:
        path = _state_path(png_dir)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("states"), dict):
                    st = {str(k): str(v) for k, v in data["states"].items()}
                    return cls(states=st)
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self, png_dir: Path | str | None) -> None:
        path = _state_path(png_dir)
        if path.parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps({"states": self.states}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def summary(self) -> str:
        parts = [f"{k}≈19|{v}" if k == "Jin" else f"{k}|{v}" for k, v in sorted(self.states.items())]
        return "; ".join(parts)

    def detect_present(
        self,
        dialogue: str,
        scene_prompt: str | None = None,
    ) -> list[str]:
        text = f"{dialogue or ''}\n{scene_prompt or ''}"
        found: list[str] = []
        low = text.lower()
        for cid, names in _DETECT:
            for n in names:
                if n.lower() in low or n in text:
                    if cid not in found:
                        found.append(cid)
                    break
        if not found:
            found.append(self.default_protagonist)
        return found

    def infer_state(self, cid: str, dialogue: str) -> str | None:
        t = dialogue or ""
        if cid == "Jin":
            if _SHOULDER_RE.search(t):
                return "wounded_shoulder"
            if _BLOOD_RE.search(t):
                return "blood_robe"
            if _TORN_RE.search(t) or _BATTLE_RE.search(t):
                return "battle_torn"
            if _HAIR_LOOSE_RE.search(t):
                return "hair_loose"
        elif cid == "Baek":
            if _BLOOD_RE.search(t):
                return "blood_robe"
            if _TORN_RE.search(t) or _BATTLE_RE.search(t):
                return "battle_torn"
        return None

    def update_from_dialogue(
        self,
        dialogue: str,
        *,
        scene_prompt: str | None = None,
    ) -> None:
        present = self.detect_present(dialogue, scene_prompt)
        for cid in present:
            if cid not in ("Jin", "Baek"):
                continue
            new = self.infer_state(cid, dialogue)
            if new:
                self.states[cid] = new

    def _jin_age(self, dialogue: str) -> int:
        if _YOUNG_JIN_RE.search(dialogue or ""):
            return 15
        return 19

    def _jin_look(self, dialogue: str) -> str:
        if _FLASHBACK_RE.search(dialogue or ""):
            return _JIN_PAST
        age = self._jin_age(dialogue)
        state = self.states.get("Jin", "base")
        body = _JIN_STATES.get(state, _JIN_STATES["base"])
        expr = "calm unreadable expression"
        if _KILLING_RE.search(dialogue or ""):
            expr = (
                "calm unreadable expression, eyes filled with restrained killing intent"
            )
        if age <= 15:
            return (
                f"Jin Muhan, approximately fifteen years old, East-Asian youth with "
                f"the soul of a fallen sword god, {_JIN_FACE}, {body}, "
                f"slender wiry build, {expr}"
            )
        return (
            f"Jin Muhan, approximately nineteen years old, East-Asian young "
            f"swordsman, {_JIN_FACE}, {body}, slender wiry build, {expr}"
        )

    def _baek_look(self) -> str:
        state = self.states.get("Baek", "base")
        body = _BAEK_STATES.get(state, _BAEK_STATES["base"])
        return (
            f"Han Baekgang, approximately nineteen years old, lean East-Asian "
            f"youth with a deceptively warm smile hiding assassin coldness, "
            f"{_BAEK_FACE}, {body}, athletic agile build"
        )

    def build_look_block(
        self,
        dialogue: str,
        scene_prompt: str | None = None,
    ) -> str:
        """매 장 명령에 붙일 CHARACTER LOOK 영문 블록."""
        present = self.detect_present(dialogue, scene_prompt)
        lines: list[str] = []
        keys: list[str] = []
        include_jin_anchor = False
        for cid in present:
            if cid == "Jin":
                lines.append(self._jin_look(dialogue))
                keys.append(f"Jin≈{self._jin_age(dialogue)}|{self.states.get('Jin', 'base')}")
                include_jin_anchor = not _FLASHBACK_RE.search(dialogue or "")
            elif cid == "Baek":
                lines.append(self._baek_look())
                keys.append(f"Baek≈19|{self.states.get('Baek', 'base')}")
            elif cid in _STATIC_LOOKS:
                lines.append(_STATIC_LOOKS[cid])
                keys.append(f"{cid}|base")
        header = f"State keys: {'; '.join(keys)}"
        block = header + "\n" + "\n".join(lines)
        if include_jin_anchor:
            block += "\n" + _JIN_ANCHOR
        return block.strip()

    def build_scene_instruction(self, label: str) -> str:
        """생성 지시 — Face/State 유지, 장면만 변경."""
        return (
            f"{label} Chinese wuxia manhua illustration — generate this scene now. "
            f"Keep Face Identity and State keys in CHARACTER LOOK identical to the "
            f"previous current-timeline scene unless dialogue changed hair/robe/wound; "
            f"only pose, action, camera, and background may change. "
            f"Do NOT redesign face, hair style, or robe colors arbitrarily. "
            f"No text, speech bubbles, bubble, tooltip, or callout in the image. "
            f"After the image appears, output exactly one line: "
            f"「{label} 이미지가 성공적으로 생성되었습니다.」 "
            f"Do not write success text without the image. "
            f"If generation fails, short error only. "
            f"No summary, verification table, continuation, or background guide."
        )


def _state_path(png_dir: Path | str | None) -> Path:
    if png_dir:
        return Path(png_dir) / ".character_state.json"
    return Path(".character_state.json")


def build_character_look_for_scene(
    srt_sec: int,
    *,
    dialogue: str = "",
    scene_prompt: str | None = None,
    png_dir: Path | str | None = None,
    tracker: CharacterStateTracker | None = None,
) -> tuple[str, CharacterStateTracker]:
    """대사·장면에서 상태 갱신 후 LOOK 블록 반환."""
    tr = tracker or CharacterStateTracker.load(png_dir)
    tr.update_from_dialogue(dialogue, scene_prompt=scene_prompt)
    look = tr.build_look_block(dialogue, scene_prompt)
    if png_dir:
        tr.save(png_dir)
    return look, tr
