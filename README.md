# Nova‑Transcriber 📝 🎧

Batch‑convert any folder of audio files into plain‑text transcripts using the **Deepgram SDK v3** with the **Nova 3** model.

* ⚡ Async + concurrent uploads (tune with `--concurrency`)
* 📊 Live progress bar (`tqdm` by default, `rich` optional)
* 💰 Per‑file and total cost estimates
* 🗂️ Input and output folders are completely separate—transcripts never overwrite audio

---

## 1 · Install

> Requires **Poetry** and **Python 3.10+**.

```bash
# Install poetry if you don't have it
# https://python-poetry.org/docs/#installation

# Clone the repository
git clone https://github.com/sdevgill/nova-transcriber.git
cd nova-transcriber

# Install dependencies
poetry install

# Activate the virtual environment
poetry shell
```

---

## 2 · Configure

Copy the template and drop in your Deepgram key (and, if pricing changes, an updated cost per minute):

```bash
cp .env.local .env
```

```dotenv
DEEPGRAM_API_KEY=dg_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
DG_RATE_PER_MIN=0.0043
```

---

## 3 · Usage

### Minimal (defaults)

```bash
python transcribe.py /path/to/audio --output-dir /path/to/text
```

### Chunked with higher parallelism

```bash
python transcribe.py /path/to/audio --output-dir /path/to/text --batch 5 --concurrency 6
```

### Fancy rich progress bar

```bash
python transcribe.py /path/to/audio --output-dir /path/to/text --batch 30 --concurrency 6 --progress rich
```

### Options

| Flag            | Default | Description                                |
|-----------------|---------|--------------------------------------------|
| `--batch`       | `50`    | Number of files to process this run        |
| `--concurrency` | `4`     | Parallel uploads to Deepgram               |
| `--timeout`     | `300`   | Per‑file HTTP timeout (seconds)            |
| `--progress`    | `tqdm`  | `tqdm` or `rich` progress bar style        |

> The script **skips** any audio that already has a matching `.txt` in the output folder, so you can rerun as many times as you like.

---

## 4 · Output

For each finished file you'll see something like:

```
✔︎ my‑audio-file.mp3   |  48.59 min |   23.0 s | $  0.2089
```

* **48.59 min** – audio duration reported by Deepgram
* **23.0 s** – wall‑clock time to transcribe
* **$0.2089** – estimated cost (`duration/60 × DG_RATE_PER_MIN`)

At the end:

```
Processed 5 files | 204.40 min audio | elapsed 70.6s | cost $0.8789
```

---

## 5 · FAQ

**Q: How do I resume later?**
A: Just rerun the command; files that already have a `.txt` sibling are ignored.

**Q: Does it work with video?**
As long as the extension is in `AUDIO_EXTS` (e.g. `.webm`), yes—Deepgram will strip the audio.

**Q: Why is the cost only an estimate?**
It multiplies the reported duration by `DG_RATE_PER_MIN`. If your Deepgram plan has different pricing, adjust the env value.

---

## 6 · License

MIT – do whatever you want, just don't blame me if your bill is high.
