"""Lectura mínima de metadatos GGUF (solo la cabecera, sin cargar el modelo).

Sirve para CTX=auto en aios-llama: contexto de entrenamiento y bytes de caché
KV por token, sacados de los metadatos del propio modelo.
"""
import struct

# Tipos de valor GGUF
_FMT = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
STRING, ARRAY = 8, 9


def _read(f, fmt):
    size = struct.calcsize("<" + fmt)
    return struct.unpack("<" + fmt, f.read(size))[0]


def _string(f):
    return f.read(_read(f, "Q")).decode("utf-8", "replace")


def _value(f, t):
    if t == STRING:
        return _string(f)
    if t == ARRAY:
        et, n = _read(f, "I"), _read(f, "Q")
        if et == STRING:
            for _ in range(n):
                f.seek(_read(f, "Q"), 1)
            return None  # listas de texto (vocabulario): no hacen falta
        if et in _FMT:
            size = struct.calcsize("<" + _FMT[et])
            if n > 4096:  # listas largas de números (p. ej. tokens): se saltan
                f.seek(size * n, 1)
                return None
            return [_read(f, _FMT[et]) for _ in range(n)]
        raise ValueError(f"unknown GGUF array type {et}")
    return _read(f, _FMT[t])


def metadata(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        _read(f, "I")  # versión
        _read(f, "Q")  # número de tensores
        n_kv = _read(f, "Q")
        meta = {}
        for _ in range(n_kv):
            key = _string(f)
            meta[key] = _value(f, _read(f, "I"))
    return meta


def model_info(path):
    """Contexto de entrenamiento y bytes de caché KV (f16) por token."""
    m = metadata(path)
    arch = m.get("general.architecture", "")
    g = lambda k, d=None: m.get(f"{arch}.{k}", d)  # noqa: E731
    layers = int(g("block_count", 0))
    heads_kv = g("attention.head_count_kv", g("attention.head_count", 0))
    if isinstance(heads_kv, list):  # por capa en algunos modelos
        heads_kv = max(heads_kv) if heads_kv else 0
    n_embd = int(g("embedding_length", 0))
    heads = int(g("attention.head_count", 1) or 1)
    k_len = int(g("attention.key_length", n_embd // heads))
    v_len = int(g("attention.value_length", n_embd // heads))
    # Modelos híbridos (Qwen3.5: atención lineal + atención completa cada N
    # capas): solo las capas de atención completa guardan caché KV
    interval = g("full_attention_interval")
    attn_layers = layers // int(interval) if interval else layers
    kv_per_token = attn_layers * int(heads_kv) * (k_len + v_len) * 2
    return {"arch": arch, "n_ctx_train": int(g("context_length", 0)),
            "layers": layers, "attention_layers": attn_layers, "kv_bytes_per_token": kv_per_token}


# Plantillas Qwen3/3.5: solo las respuestas posteriores a la última pregunta del
# usuario llevan el bloque <think>; al llegar otra pregunta, las anteriores se
# pintan sin él. El prefijo cambia y llama-server, que en modelos híbridos solo
# puede volver a un checkpoint cercano al final, procesa casi toda la conversación
# de nuevo en cada mensaje (90-120 s en el HP 15s). Con el bloque en todas, la
# conversación pintada no cambia: sin razonamiento queda "<think>\n\n</think>",
# lo mismo que pone el prompt de generación con enable_thinking=false.
_THINK_ONLY_LAST = "{%- if loop.index0 > ns.last_query_index %}"
_THINK_ALWAYS = "{%- if true %}"


def stable_template(path):
    """Plantilla del modelo con el historial estable, o None si no hace falta."""
    tpl = metadata(path).get("tokenizer.chat_template")
    if not isinstance(tpl, str) or tpl.count(_THINK_ONLY_LAST) != 1:
        return None
    return tpl.replace(_THINK_ONLY_LAST, _THINK_ALWAYS)


GIB = 1024 ** 3
RESERVE = 1.5 * GIB   # sistema, sway, terminal y algo de caché de disco
COMPUTE = 0.5 * GIB   # búferes de cálculo de llama.cpp
STEP = 4096


def mem_total():
    for line in open("/proc/meminfo"):
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return 8 * GIB


def auto_context(model, mmproj=None, total=None):
    """Contexto que cabe en la RAM de este equipo, con tope por velocidad.

    En CPU, un contexto enorme hace eterno procesar el prompt: 16K con menos
    de 12 GiB de RAM (perfil mínimo), 32K con más (perfil recomendado).
    """
    import os
    info = model_info(model)
    total = total or mem_total()
    weights = os.path.getsize(model) + (os.path.getsize(mmproj) if mmproj else 0)
    kv_budget = total - RESERVE - weights - COMPUTE
    fits = int(kv_budget // info["kv_bytes_per_token"]) if info["kv_bytes_per_token"] else 0
    cap = 16384 if total < 12 * GIB else 32768
    limits = [fits, cap] + ([info["n_ctx_train"]] if info["n_ctx_train"] else [])
    ctx = max(STEP, min(limits) // STEP * STEP)
    why = (f"RAM {total / GIB:.1f} GiB, weights {weights / GIB:.1f} GiB, "
           f"KV {info['kv_bytes_per_token'] // 1024} KiB/token -> fits {fits}, cap {cap}, "
           f"trained {info['n_ctx_train']}")
    return ctx, why


if __name__ == "__main__":
    # aios-llama: python3 gguf.py auto <modelo> [mmproj]  -> contexto en tokens
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "auto":
        n, why = auto_context(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None)
        print(n)
        print(f"auto context {n}: {why}", file=sys.stderr)
    elif len(sys.argv) == 4 and sys.argv[1] == "template":
        # aios-llama: python3 gguf.py template <modelo> <salida>; código 1 = no hace falta
        tpl = stable_template(sys.argv[2])
        if tpl is None:
            sys.exit(1)
        with open(sys.argv[3], "w") as f:
            f.write(tpl)
    else:
        sys.exit("usage: gguf.py auto <model.gguf> [mmproj.gguf] | template <model.gguf> <out.jinja>")
