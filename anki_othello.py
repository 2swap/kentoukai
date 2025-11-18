import re
import subprocess
import sys
import time
from pathlib import Path

import requests

# ---------- CONFIG ----------
EDAX_DIRECTORY = "../edax"
EDAX_FILENAME = "lEdax-x86-64"
EVAL_SWING_THRESHOLD = 5 # points difference to count as a blunder
# ----------------------------

def run_edax(play_command):
    """Send commands to EDAX and return output."""
    proc = subprocess.Popen(
        [f"./{EDAX_FILENAME}"],
        cwd=EDAX_DIRECTORY,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Only request the best move
    out, err = proc.communicate("level 30\n" + play_command + "hint 1\n")

    if err:
        print("EDAX error:", err.strip())

    try:
        proc.kill()
    except Exception:
        pass

    return out

def parse_hint_output(output):
    """Parse EDAX output and extract best move and evaluation."""
    for line in output.splitlines():
        m = re.match(r".*?\d+@\d+%\s+([+-]?\d+).*?\s([A-Ha-h][1-8])", line)
        if m:
            try:
                score = int(m.group(1))
            except ValueError:
                score = None
            move = m.group(2).upper()
            return move, score
    return None, None


def analyze_single_move(before_moves, after_moves):
    """Analyze a single move (difference between before and after arrays)."""
    if len(after_moves) != len(before_moves) + 1:
        print("Invalid move file: not exactly one move added.")
        return None

    played_move = after_moves[-1]
    color = "B" if len(before_moves) % 2 == 0 else "W"

    play_cmd_before = ("play " + " ".join(before_moves) + "\n") if before_moves else ""
    play_cmd_after = "play " + " ".join(after_moves) + "\n"

    # Evaluate best move from BEFORE position
    raw_before = run_edax(play_cmd_before)
    best_move_before, eval_best_move = parse_hint_output(raw_before)

    # Evaluate best reply from AFTER position
    raw_after = run_edax(play_cmd_after)
    best_reply_after_actual, eval_after_reply = parse_hint_output(raw_after)

    if eval_best_move is None or eval_after_reply is None or best_move_before is None or best_reply_after_actual is None:
        print("Could not parse EDAX output properly.")
        return None

    delta = eval_best_move + eval_after_reply

    row = {
        "color": color,
        "played": played_move,
        "eval_best_move": eval_best_move,
        "best_move_before": best_move_before or "-",
        "eval_after_reply": eval_after_reply,
        "best_reply_after_actual": best_reply_after_actual or "-",
        "delta": delta,
    }

    print("-" * 72)
    print(f"Color: {color}, Played: {played_move}")
    print(f"Eval(best): {eval_best_move:>4}, BestMove: {best_move_before}")
    print(f"Eval(after reply): {eval_after_reply:>4}, BestReply: {best_reply_after_actual}")
    print(f"Δ = {delta:+d}")
    print("-" * 72)

    return row


def add_anki_card(sequence_fenish, correct_move):
    ANKI_CONNECT_URL = "http://localhost:8765"
    payload = {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": {
                "deckName": "Othello",
                "modelName": "Othello",
                "fields": {
                    "Sequence": sequence_fenish,
                    "Solution": correct_move,
                },
            }
        },
    }
    try:
        resp = requests.post(ANKI_CONNECT_URL, json=payload, timeout=5)
        if resp.ok:
            print(f"✅ Added card: pos='{sequence_fenish}' -> {correct_move}")
        else:
            print(f"⚠️ Failed to add card: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"⚠️ Error contacting AnkiConnect: {e}")


def process_one_move_file(file_path):
    """Handle a single .othello file (two-line format)."""
    text = Path(file_path).read_text().strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if len(lines) != 2:
        print(f"Invalid file format in {file_path}: expected exactly two lines.")
        return

    before_moves = re.findall(r"\b[A-H][1-8]\b", lines[0].upper())
    after_moves = re.findall(r"\b[A-H][1-8]\b", lines[1].upper())

    if not after_moves:
        print(f"No moves found in {file_path}.")
        return

    row = analyze_single_move(before_moves, after_moves)

    if row is not None and row["delta"] >= EVAL_SWING_THRESHOLD:
        correct_move = row["best_move_before"]
        if correct_move and correct_move != "-":
            seq_before_str = "".join(before_moves)
            add_anki_card(seq_before_str, correct_move)
        else:
            print("No valid best move to add as Anki card.")

    # Delete the file once processed
    try:
        Path(file_path).unlink()
        print(f"Deleted move file: {file_path}")
    except Exception as e:
        print(f"Could not delete game file: {e}")


def main():
    # Check anki is running before proceeding
    try:
        resp = requests.post("http://localhost:8765", json={"action": "version", "version": 6}, timeout=5)
        if not resp.ok:
            print("AnkiConnect is not responding properly. Please ensure Anki is running with AnkiConnect installed.")
            return
    except Exception:
        print("Could not connect to AnkiConnect. Please ensure Anki is running with AnkiConnect installed.")
        return

    othello_files = sorted(Path.home().joinpath("Downloads").glob("*.othello"))
    if not othello_files:
        print("No .othello files found in the downloads folder.")
        return

    for f in othello_files:
        print(f"\nProcessing file: {f}")
        process_one_move_file(f)


if __name__ == "__main__":
    main()

