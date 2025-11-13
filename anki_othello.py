import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from prettytable import PrettyTable

# ---------- CONFIG ----------
EDAX_DIRECTORY = "edax"
EDAX_FILENAME = "lEdax-x86-64"
EVAL_SWING_THRESHOLD = 10  # points difference to count as a blunder
# ----------------------------

def run_edax(play_command):
    """Send commands to edax and return output."""
    proc = subprocess.Popen(
        [f"./{EDAX_FILENAME}"],
        cwd=EDAX_DIRECTORY,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    # Only request the best move
    out, err = proc.communicate("level 25\n" + play_command + "hint 1\n")

    if err:
        print("EDAX error:", err)

    try:
        proc.kill()
    except Exception:
        pass

    return out

def parse_hint_output(output):
    best_move = None
    score = None
    for line in output.splitlines():
        # Try to find: ... <num>@<num>% [+-]?<score> <move>
        m = re.match(r".*?\d+@\d+%\s+([+-]?\d+).*?\s([A-Ha-h][1-8])", line)
        if m:
            try:
                score = int(m.group(1))
            except ValueError:
                score = None
            best_move = m.group(2).upper()
            return best_move, score
    return None, None


def analyze_game(moves):
    rows = []
    color = "B"

    for i, move in enumerate(moves):
        # Only analyze the first 16 moves
        if i >= 16:
            break
        seq_before = moves[:i]          # position before this move is played
        seq_after_actual = moves[:i+1]  # position after the actual move is played

        play_cmd_before = ("play " + " ".join(seq_before) + "\n") if seq_before else ""
        play_cmd_after = ("play " + " ".join(seq_after_actual) + "\n")

        # Query EDAX for best from the position BEFORE the move
        raw_before = run_edax(play_cmd_before)
        best_move_before, eval_best_move = parse_hint_output(raw_before)
        if eval_best_move is None:
            eval_best_move = 0

        # Query EDAX for best reply from the position AFTER the actual move
        raw_after = run_edax(play_cmd_after)
        best_reply_after_actual, eval_after_reply = parse_hint_output(raw_after)
        if eval_after_reply is None:
            eval_after_reply = 0

        # Compute delta as described: eval_best_move + eval_after_reply
        delta = eval_best_move + eval_after_reply

        rows.append({
            "index": i+1,
            "color": color,
            "played": move,
            "eval_best_move": eval_best_move,
            "best_move_before": best_move_before or "-",
            "eval_after_reply": eval_after_reply,
            "best_reply_after_actual": best_reply_after_actual or "-",
            "delta": delta,
        })

        # flip color
        color = "W" if color == "B" else "B"

    # Print nicely formatted table
    hdr = (
        f"{'#':>3}  {'C':>1}  {'Played':>6}  {'Eval(best)':>10}  {'Best@Before':>12}  "
        f"{'Eval(after reply)':>16}  {'BestReply':>10}  {'Δ':>6}"
    )
    sep = "-" * len(hdr)
    print(sep)
    print(hdr)
    print(sep)
    for r in rows:
        print(
            f"{r['index']:3d}  {r['color']:1s}  {r['played']:6s}  "
            f"{r['eval_best_move']:10d}  {r['best_move_before']:12s}  "
            f"{r['eval_after_reply']:16d}  {r['best_reply_after_actual']:10s}  "
            f"{r['delta']:6d}"
        )
    print(sep)

    # Second pass: identify blunders
    blunders = [r for r in rows if r['delta'] >= EVAL_SWING_THRESHOLD]

    return rows, blunders


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
                    "Solution": correct_move
                },
            }
        }
    }
    try:
        resp = requests.post(ANKI_CONNECT_URL, json=payload, timeout=5)
        if resp.ok:
            print(f"✅ Added card: pos='{sequence_fenish}' -> {correct_move}")
        else:
            print(f"⚠️ Failed to add card: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"⚠️ Error contacting AnkiConnect: {e}")


def process_one_game(file_path):
    text = Path(file_path).read_text()
    moves = re.findall(r"\b[A-H][1-8]\b", text.upper())
    if not moves:
        print("No moves found in file.")
        return

    print(f"Found {len(moves)} moves.")
    rows, blunders = analyze_game(moves)
    print(f"\nDetected {len(blunders)} blunders.\n")

    for b in blunders:
        idx = b["index"]  # 1-based move number
        # seq_before for this move was moves[:idx-1] (since index = i+1 and seq_before = moves[:i])
        seq_before_list = moves[: idx - 1]
        seq_before_str = "".join(seq_before_list)
        correct_move = b.get("best_move_before")
        if not correct_move or correct_move == "-":
            print(f"Skipping blunder at move {idx}: no engine-recommended move found.")
            continue

        add_anki_card(seq_before_str, correct_move)
        time.sleep(0.5)

    # Delete the game file
    try:
        Path(file_path).unlink()
        print(f"Deleted game file: {file_path}")
    except Exception as e:
        print(f"Could not delete game file: {e}")

def main():
    # Process all .othello files in the current directory
    othello_files = list(Path(".").glob("*.othello"))
    if not othello_files:
        print("No .othello files found in the current directory.")
        return
    for file_path in othello_files:
        print(f"\nProcessing file: {file_path}")
        process_one_game(file_path)

if __name__ == "__main__":
    main()
