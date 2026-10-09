"""Diktatūra — kolegų garso (R) nuotėkio šalinimas iš mikrofono kanalo (L). Tik numpy; offline, prieš loudnorm.

Kodėl (matuota 2026-10-09, HP EliteBook 850 G8 / Realtek ALC285, laidinės ausinės su mikrofonu kombinuotame lizde):
L kanale yra TIESINĖ R kopija -20…-28 dB (koherencija iki 0.9, dažnių atsakas plokščias 100 Hz–1.6 kHz) — elektrinis
persiklojimas lizde (bendras įžeminimas), proporcingas ausinių garsumui; ALSA / PulseAudio loopback'o nėra, tad
„kita tvarkyklė" jo nepašalina. Po loudnorm Whisper jį išgirsta -> „Tu" eilutės su kolegų žodžiais.
Be to, įraše L atsilieka nuo R ~0.5–1 s (ffmpeg dviejų pulse srautų startas — poslinkis kinta, todėl skaičiuojamas
kiekvienam įrašui).

Kaip: (1) poslinkis — normuota kryžminė koreliacija kelių garsiausių R blokų (±2 s), mediana; (2) nuotėkio kelias
H(f) = Σ L·conj(R) / Σ |R|² per visą įrašą (laike pastovus — tinka elektriniam persiklojimui), trumpas FIR h;
(3) L' = L − h * R(t − poslinkis). Atminčiai — blokais. Nuotėkio nerasta (koreliacija silpna) -> L nekeičiamas.
"""
import numpy as np

SR = 16000
NFFT = 512                 # FIR ilgis (32 ms): elektriniam keliui pakanka, akustiniam (ausinės) — irgi
MIN_STRENGTH = 0.08        # silpnesnė koreliacija = nuotėkio nėra (triukšmas) -> nieko nedaroma
MAX_LAG_SEC = 2.0


def _blocks(R, sr, block_sec, n_blocks, margin):
    """Garsiausių (pagal R) nepersidengiančių blokų pradžios."""
    B = int(block_sec * sr)
    starts = list(range(margin, len(R) - B - margin + 1, B))
    if not starts:
        return [], B
    energy = [float(np.mean(R[a:a + B] ** 2)) for a in starts]
    order = np.argsort(energy)[::-1][:n_blocks]
    return [starts[i] for i in sorted(order) if energy[i] > 1e-7], B


def estimate_lag(L, R, sr=SR, max_lag_sec=MAX_LAG_SEC, block_sec=10.0, n_blocks=8):
    """-> (poslinkis mėginiais | None, stiprumas 0..1). Poslinkis > 0: L atsilieka (L[n] ≈ g·R[n − poslinkis]).
    Trumpam įrašui (pvz. 6 s VOX gabalas skambučio metu) blokas ir paieškos ribos sumažinami."""
    M = min(int(max_lag_sec * sr), len(R) // 4)
    block_sec = min(block_sec, (len(R) - 2 * M) / sr)
    if block_sec < 2.0:
        return None, 0.0
    starts, B = _blocks(R, sr, block_sec, n_blocks, M)
    found = []
    for a in starts:
        l = L[a:a + B].astype(np.float64)
        r = R[a - M:a + B + M].astype(np.float64)
        l -= l.mean()
        r -= r.mean()
        n = 1 << int(np.ceil(np.log2(len(l) + len(r))))
        c = np.fft.irfft(np.fft.rfft(r, n) * np.conj(np.fft.rfft(l, n)), n)[:2 * M + 1]   # c[j] = Σ l[i]·r[i + j]
        # normuota: kiekvienam j — atitinkamo r lango energija (slenkanti suma)
        cs = np.concatenate([[0.0], np.cumsum(r ** 2)])
        er = cs[B:B + 2 * M + 1] - cs[:2 * M + 1]
        norm = np.sqrt(er * float(np.dot(l, l))) + 1e-12
        cn = np.abs(c) / norm
        j = int(np.argmax(cn))
        found.append((float(cn[j]), M - j))
    if len(found) == 1:                     # trumpas įrašas — vienas blokas: reikalaujam stipresnio sutapimo
        s, lag = found[0]
        return (lag, s) if s >= 2 * MIN_STRENGTH else (None, s)
    need = max(2, len(found) // 2)          # keli blokai turi sutarti dėl to paties poslinkio
    good = [lag for s, lag in found if s >= MIN_STRENGTH]
    if len(good) < need:
        return None, max((s for s, _ in found), default=0.0)
    lag = int(np.median(good))
    consistent = [s for s, k in found if abs(k - lag) <= 2]
    return (lag, float(np.median(consistent))) if len(consistent) >= need else (None, 0.0)


def shifted(R, lag):
    """x[n] = R[n − lag] (nuliai už ribų)."""
    x = np.zeros_like(R)
    if lag >= 0:
        x[lag:] = R[:len(R) - lag]
    else:
        x[:len(R) + lag] = R[-lag:]
    return x


def _frames(x, nfft, hop, start, count):
    idx = start + np.arange(count)[:, None] * hop + np.arange(nfft)[None, :]
    return x[idx]


def _accumulate(L, x, nfft, hop, win, batch, H0=None, ratio=2.0):
    """Σ Y·conj(X), Σ |X|², Σ |Y|². Su H0 — tik kadrai, kuriuose L beveik vien nuotėkis (|Y − H0·X|² ≤ ratio·|H0·X|²):
    tavo kalba (dvigubas kalbėjimas) filtro įvertinimui — tik triukšmas."""
    nfr = (len(L) - nfft) // hop
    sxy = np.zeros(nfft // 2 + 1, np.complex128)
    sxx = np.zeros(nfft // 2 + 1)
    syy = np.zeros(nfft // 2 + 1)
    used = 0
    for s in range(0, max(nfr, 0), batch):
        cnt = min(batch, nfr - s)
        X = np.fft.rfft(_frames(x, nfft, hop, s * hop, cnt) * win, axis=1)
        Y = np.fft.rfft(_frames(L, nfft, hop, s * hop, cnt) * win, axis=1)
        if H0 is not None:
            P = H0[None, :] * X
            keep = np.sum(np.abs(Y - P) ** 2, axis=1) <= ratio * np.sum(np.abs(P) ** 2, axis=1)
            X, Y = X[keep], Y[keep]
        used += len(X)
        sxy += np.sum(Y * np.conj(X), axis=0)
        sxx += np.sum(np.abs(X) ** 2, axis=0)
        syy += np.sum(np.abs(Y) ** 2, axis=0)
    return sxy, sxx, syy, used


def estimate_path(L, x, nfft=NFFT, batch=4096):
    """Nuotėkio kelias: (FIR h (centruotas, ilgis nfft), koherencija pagal dažnį). x — jau paslinktas R.
    Du etapai: visi kadrai -> H0; tada tik kadrai, kur L ≈ nuotėkis (tu tyli) -> H (tikslesnis)."""
    hop = nfft // 2
    win = np.hanning(nfft).astype(np.float32)
    sxy, sxx, syy, n = _accumulate(L, x, nfft, hop, win, batch)
    H = sxy / (sxx + 1e-12)
    coh = np.abs(sxy) ** 2 / (sxx * syy + 1e-20)
    sxy2, sxx2, _, n2 = _accumulate(L, x, nfft, hop, win, batch, H0=H)
    if n2 >= max(50, n // 20):
        H = sxy2 / (sxx2 + 1e-12)
    h = np.roll(np.fft.irfft(H, nfft), nfft // 2) * np.hanning(nfft)     # centruotas (leidžia ir ±kelis mėginius)
    return h.astype(np.float32), coh


def apply_path(L, x, h, chunk=1 << 20):
    """L − h * x (h centruotas: vėlinimas len(h)//2), blokais (overlap-add)."""
    d = len(h) // 2
    out = L.astype(np.float32).copy()
    n = 1 << int(np.ceil(np.log2(chunk + len(h))))
    Hf = np.fft.rfft(h, n)
    for a in range(0, len(x), chunk):
        seg = x[a:a + chunk]
        y = np.fft.irfft(np.fft.rfft(seg, n) * Hf, n)[:len(seg) + len(h) - 1]
        lo, hi = a - d, a - d + len(y)                     # y[i] atitinka out[a + i − d]
        s0, s1 = max(lo, 0), min(hi, len(out))
        if s1 > s0:
            out[s0:s1] -= y[s0 - lo:s1 - lo]
    return out


def leak_db(L, x, nfft=NFFT):
    """Kiek L yra x kopijos (dB nuo x lygio), matuojant koherentišką dalį — prieš/po palyginimui."""
    h, coh = estimate_path(L, x, nfft)
    return float(20 * np.log10(np.sqrt(np.sum(h.astype(np.float64) ** 2)) + 1e-9)), float(np.median(coh[8:200]))


def cancel(L, R, sr=SR):
    """-> (išvalytas L, info). Nuotėkio nerasta -> (L, {"applied": False, ...})."""
    lag, strength = estimate_lag(L, R, sr)
    if lag is None:
        return L, {"applied": False, "strength": round(strength, 3)}
    x = shifted(R.astype(np.float32), lag)
    h, coh = estimate_path(L.astype(np.float32), x)
    out = apply_path(L, x, h)
    return out, {"applied": True, "lag_ms": round(lag / sr * 1000, 1), "strength": round(strength, 3),
                 "path_db": round(float(20 * np.log10(np.sqrt(np.sum(h.astype(np.float64) ** 2)) + 1e-9)), 1),
                 "coherence": round(float(np.median(coh[8:200])), 2)}
