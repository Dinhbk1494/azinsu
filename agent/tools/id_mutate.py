import base64
import uuid
import re
from agent.tools.base import BaseTool


def _try_decode(value: str) -> tuple[str | None, str]:
    # base64
    try:
        decoded = base64.b64decode(value + "==").decode()
        if decoded.isdigit() or re.match(r'^\w+$', decoded):
            return decoded, "base64"
    except Exception:
        pass
    # hex
    try:
        if re.match(r'^[0-9a-fA-F]+$', value) and len(value) % 2 == 0:
            decoded = bytes.fromhex(value).decode()
            if decoded.isdigit():
                return decoded, "hex"
    except Exception:
        pass
    return None, ""


def _encode_back(value: str, encoding: str) -> str:
    if encoding == "base64":
        return base64.b64encode(value.encode()).decode().rstrip("=")
    elif encoding == "hex":
        return value.encode().hex()
    return value


class IdMutateTool(BaseTool):
    name = "id_mutate"

    ALL_STRATEGIES = [
        "sequential_increment",
        "sequential_decrement",
        "boundary",
        "random_in_range",
        "user_b_ids",
        "decode_then_mutate",
        "base64_mutate",
        "hex_mutate",
        "uuid_v4_random",
        "null_byte",
        "array_wrap",
        "string_to_int",
        "negative_value",
        "float_value",
        "leading_zeros",
        "oversized",
        "path_traversal",
        "case_variation",
    ]

    def run(self, original_value: str, strategies: list[str] | None = None,
            user_b_known_ids: list[str] | None = None) -> dict:
        strategies = strategies or self.ALL_STRATEGIES
        mutations: list[dict] = []

        orig = str(original_value)

        for strategy in strategies:
            new_mutations = self._apply(strategy, orig, user_b_known_ids or [])
            mutations.extend(new_mutations)

        # Deduplicate by value
        seen: set[str] = set()
        unique: list[dict] = []
        for m in mutations:
            if m["value"] not in seen and m["value"] != orig:
                seen.add(m["value"])
                unique.append(m)

        return {"mutations": unique}

    def _apply(self, strategy: str, orig: str, user_b_ids: list[str]) -> list[dict]:
        m = []

        if strategy == "sequential_increment" and orig.isdigit():
            base = int(orig)
            for delta in [1, 2, 3, 5, 10, 100]:
                m.append({"value": str(base + delta), "strategy": strategy, "rationale": f"{orig}+{delta}"})

        elif strategy == "sequential_decrement" and orig.isdigit():
            base = int(orig)
            for delta in [1, 2, 3]:
                if base - delta > 0:
                    m.append({"value": str(base - delta), "strategy": strategy, "rationale": f"{orig}-{delta}"})

        elif strategy == "boundary":
            for v in ["0", "1", "-1", "2147483647", "9999999"]:
                m.append({"value": v, "strategy": strategy, "rationale": "boundary value"})

        elif strategy == "random_in_range" and orig.isdigit():
            import random
            base = int(orig)
            rng = max(1, base * 2)
            for _ in range(5):
                v = random.randint(1, rng)
                m.append({"value": str(v), "strategy": strategy, "rationale": "random in range"})

        elif strategy == "user_b_ids" and user_b_ids:
            for uid in user_b_ids:
                m.append({"value": str(uid), "strategy": strategy, "rationale": "known user B ID"})

        elif strategy == "decode_then_mutate":
            decoded, encoding = _try_decode(orig)
            if decoded and decoded.isdigit():
                base = int(decoded)
                for delta in [1, 2, -1]:
                    new_val = _encode_back(str(base + delta), encoding)
                    m.append({"value": new_val, "strategy": strategy, "rationale": f"decoded {encoding} → mutated"})

        elif strategy == "base64_mutate":
            if orig.isdigit():
                for v in [str(int(orig) + 1), str(int(orig) + 2)]:
                    encoded = base64.b64encode(v.encode()).decode().rstrip("=")
                    m.append({"value": encoded, "strategy": strategy, "rationale": f"base64({v})"})
            # Try decoding orig as base64
            try:
                dec = base64.b64decode(orig + "==").decode()
                if dec.isdigit():
                    new_v = base64.b64encode(str(int(dec) + 1).encode()).decode().rstrip("=")
                    m.append({"value": new_v, "strategy": strategy, "rationale": f"re-encoded base64"})
            except Exception:
                pass

        elif strategy == "hex_mutate":
            if orig.isdigit():
                for v in [int(orig) + 1, int(orig) - 1]:
                    if v > 0:
                        m.append({"value": hex(v), "strategy": strategy, "rationale": f"hex({v})"})

        elif strategy == "uuid_v4_random":
            for _ in range(3):
                m.append({"value": str(uuid.uuid4()), "strategy": strategy, "rationale": "random UUID"})

        elif strategy == "null_byte":
            m.append({"value": orig + "\x00", "strategy": strategy, "rationale": "null byte suffix"})
            m.append({"value": orig + "%00", "strategy": strategy, "rationale": "URL null byte"})

        elif strategy == "array_wrap":
            m.append({"value": f"[{orig}]", "strategy": strategy, "rationale": "wrapped in array"})

        elif strategy == "string_to_int":
            if orig.isdigit():
                m.append({"value": f'"{orig}"', "strategy": strategy, "rationale": "int to string"})
            else:
                try:
                    m.append({"value": str(int(orig)), "strategy": strategy, "rationale": "string to int"})
                except Exception:
                    pass

        elif strategy == "negative_value" and orig.isdigit():
            m.append({"value": f"-{orig}", "strategy": strategy, "rationale": "negative"})

        elif strategy == "float_value" and orig.isdigit():
            m.append({"value": f"{orig}.0", "strategy": strategy, "rationale": "float version"})
            m.append({"value": f"{orig}.1", "strategy": strategy, "rationale": "float +0.1"})

        elif strategy == "leading_zeros" and orig.isdigit():
            m.append({"value": "0" + orig, "strategy": strategy, "rationale": "leading zero"})
            m.append({"value": "00" + orig, "strategy": strategy, "rationale": "double leading zero"})

        elif strategy == "oversized":
            m.append({"value": "99999999999", "strategy": strategy, "rationale": "oversized int"})
            m.append({"value": "A" * 50, "strategy": strategy, "rationale": "oversized string"})

        elif strategy == "path_traversal":
            m.append({"value": f"../{orig}", "strategy": strategy, "rationale": "path traversal"})
            m.append({"value": f"..%2f{orig}", "strategy": strategy, "rationale": "URL-encoded path traversal"})

        elif strategy == "case_variation":
            m.append({"value": orig.upper(), "strategy": strategy, "rationale": "uppercase"})
            m.append({"value": orig.lower(), "strategy": strategy, "rationale": "lowercase"})

        return m
