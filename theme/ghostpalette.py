"""
GHOSTBOARD OS — chargement de la palette et utilitaires couleur.

Module partagé par tous les générateurs. Il ne contient AUCUNE couleur :
tout vient de brand/palette.toml. Voir ce fichier pour la doctrine.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

try:
    import tomllib  # Python >= 3.11 (Debian 13 = 3.13)
except ModuleNotFoundError:  # pragma: no cover - repli pour vieux Python
    import tomli as tomllib  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PALETTE = REPO_ROOT / "brand" / "palette.toml"


# --------------------------------------------------------------------------
#  Couleur
# --------------------------------------------------------------------------
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(a: str, b: str, t: float) -> str:
    """Mélange linéaire de deux hex. t=0 -> a, t=1 -> b."""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def rgba(h: str, alpha: float) -> str:
    """Hex -> chaîne CSS rgba()."""
    r, g, b = hex_to_rgb(h)
    return f"rgba({r},{g},{b},{alpha:g})"


def relative_luminance(h: str) -> float:
    def chan(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """Ratio de contraste WCAG. Sur une dalle 4 pouces, ce n'est pas
    un détail d'accessibilité : c'est de la lisibilité pure."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# --------------------------------------------------------------------------
#  Palette
# --------------------------------------------------------------------------
class Palette:
    """Vue en lecture seule de brand/palette.toml, plus les valeurs dérivées.

    Les valeurs dérivées (survol, sélection, ombres) ne sont JAMAIS écrites à
    la main : elles se recalculent depuis les 7 couleurs de base. C'est ce qui
    permet de changer un seul hex et de re-thémer tout le système.
    """

    def __init__(self, path: Path | str = DEFAULT_PALETTE):
        self.path = Path(path)
        with self.path.open("rb") as fh:
            self.data = tomllib.load(fh)

        self.meta = self.data["meta"]
        self.c = self.data["color"]
        self.mica = self.data["mica"]
        self.font = self.data["font"]
        self.layout = self.data["layout"]
        self.boot = self.data["boot"]
        self.term = self.data["terminal"]

        # ---- valeurs dérivées ------------------------------------------------
        bg, panel, accent = self.c["bg"], self.c["panel"], self.c["accent"]
        sep, text, dim = self.c["separator"], self.c["text"], self.c["text_dim"]

        self.d = {
            # surfaces
            "surface": mix(bg, panel, 0.6),        # champs, listes
            "hover": mix(panel, accent, 0.14),     # survol discret
            "active": mix(panel, accent, 0.24),    # élément actif
            "pressed": mix(panel, accent, 0.34),
            "border": sep,
            "border_focus": accent,
            # accent
            "accent_dim": mix(accent, bg, 0.45),
            "accent_bright": mix(accent, "#FFFFFF", 0.22),
            "on_accent": bg,                        # texte posé SUR l'accent
            # texte
            "text_disabled": mix(dim, bg, 0.45),
            "selection_bg": accent,
            "selection_fg": bg,
            # sémantique
            "error": self.c["input"],
            "error_dim": mix(self.c["input"], bg, 0.5),
        }

    # -- raccourcis ----------------------------------------------------------
    def __getitem__(self, key: str) -> str:
        if key in self.c:
            return self.c[key]
        return self.d[key]

    @property
    def theme_id(self) -> str:
        return self.meta["theme_id"]

    def px_to_pt(self, px: float) -> float:
        """96 dpi. XFCE et GTK raisonnent en points pour les polices."""
        return round(px * 72.0 / 96.0, 1)

    def flat(self) -> dict:
        """Tout à plat, pour la substitution de gabarits {{cle}}."""
        out: dict[str, object] = {}
        for k, v in self.meta.items():
            out[f"meta.{k}"] = v
        for k, v in self.c.items():
            out[k] = v
            out[f"color.{k}"] = v
            r, g, b = hex_to_rgb(v)
            out[f"{k}.r"], out[f"{k}.g"], out[f"{k}.b"] = r, g, b
            out[f"{k}.rgb"] = f"{r},{g},{b}"
        for k, v in self.d.items():
            out[k] = v
        for section, name in ((self.mica, "mica"), (self.font, "font"),
                              (self.layout, "layout"), (self.boot, "boot"),
                              (self.term, "term")):
            for k, v in section.items():
                out[f"{name}.{k}"] = v
        out["font.ui_pt"] = self.px_to_pt(self.font["ui_size_px"])
        out["font.title_pt"] = self.px_to_pt(self.font["title_size_px"])
        out["font.term_pt"] = self.px_to_pt(self.font["term_size_px"])
        return out


def render_template(text: str, values: dict) -> str:
    """Substitution {{cle}} minimaliste — pas de moteur de gabarit à installer."""
    out = text
    for key in sorted(values, key=len, reverse=True):
        out = out.replace("{{" + key + "}}", str(values[key]))
    if "{{" in out:
        leftovers = {
            seg.split("}}")[0] for seg in out.split("{{")[1:] if "}}" in seg
        }
        raise KeyError(f"clés de gabarit non résolues : {sorted(leftovers)}")
    return out


# --------------------------------------------------------------------------
#  Écriture PNG en Python pur
#  Volontairement sans ImageMagick ni Cairo : générer les boutons de fenêtre
#  ne doit pas coûter 120 Mo de dépendances sur un OS qui vise la légèreté.
# --------------------------------------------------------------------------
def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    """`pixels` : RGBA 8 bits, longueur width*height*4."""
    assert len(pixels) == width * height * 4, "taille de tampon RGBA invalide"
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filtre de ligne PNG : None
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


class Canvas:
    """Micro-rasteriseur RGBA avec suréchantillonnage.

    Assez pour des croix, des carrés et des tirets — c'est tout ce dont les
    boutons de fenêtre ont besoin. On dessine à `scale`x puis on réduit en
    moyennant : anti-aliasing correct sans bibliothèque graphique.
    """

    def __init__(self, width: int, height: int, scale: int = 4):
        self.w, self.h, self.s = width, height, scale
        self.buf = bytearray(width * scale * height * scale * 4)

    def _put(self, x: int, y: int, rgb, alpha: float) -> None:
        W, H = self.w * self.s, self.h * self.s
        if not (0 <= x < W and 0 <= y < H) or alpha <= 0:
            return
        i = (y * W + x) * 4
        src_a = min(1.0, alpha)
        dst_a = self.buf[i + 3] / 255.0
        out_a = src_a + dst_a * (1 - src_a)
        if out_a <= 0:
            return
        for k in range(3):
            dst = self.buf[i + k] / 255.0
            val = (rgb[k] / 255.0 * src_a + dst * dst_a * (1 - src_a)) / out_a
            self.buf[i + k] = int(round(val * 255))
        self.buf[i + 3] = int(round(out_a * 255))

    def fill_rect(self, x0, y0, x1, y1, color: str, alpha: float = 1.0) -> None:
        rgb = hex_to_rgb(color)
        s = self.s
        for y in range(int(y0 * s), int(y1 * s)):
            for x in range(int(x0 * s), int(x1 * s)):
                self._put(x, y, rgb, alpha)

    def line(self, x0, y0, x1, y1, color: str, width: float = 1.0,
             alpha: float = 1.0) -> None:
        """Segment épais, testé par distance point-segment (bords doux)."""
        rgb = hex_to_rgb(color)
        s = self.s
        ax, ay, bx, by = x0 * s, y0 * s, x1 * s, y1 * s
        half = width * s / 2.0
        minx, maxx = int(min(ax, bx) - half - 1), int(max(ax, bx) + half + 2)
        miny, maxy = int(min(ay, by) - half - 1), int(max(ay, by) + half + 2)
        dx, dy = bx - ax, by - ay
        seg_len2 = dx * dx + dy * dy or 1.0
        for y in range(miny, maxy):
            for x in range(minx, maxx):
                px, py = x + 0.5, y + 0.5
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
                d = ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5
                if d <= half:
                    self._put(x, y, rgb, alpha)

    def downsample(self) -> bytearray:
        """Réduction par moyenne s×s — c'est l'anti-aliasing."""
        s, W = self.s, self.w * self.s
        out = bytearray(self.w * self.h * 4)
        n = s * s
        for y in range(self.h):
            for x in range(self.w):
                acc = [0, 0, 0, 0]
                for sy in range(s):
                    row = ((y * s + sy) * W + x * s) * 4
                    for sx in range(s):
                        i = row + sx * 4
                        a = self.buf[i + 3]
                        acc[0] += self.buf[i] * a
                        acc[1] += self.buf[i + 1] * a
                        acc[2] += self.buf[i + 2] * a
                        acc[3] += a
                o = (y * self.w + x) * 4
                if acc[3]:
                    for k in range(3):
                        out[o + k] = min(255, acc[k] // acc[3])
                out[o + 3] = acc[3] // n
        return out

    def save(self, path: Path) -> None:
        write_png(path, self.w, self.h, self.downsample())
