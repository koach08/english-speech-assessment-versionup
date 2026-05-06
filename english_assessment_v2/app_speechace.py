# app_speechace.py - Speechace版 パワーアップ版 v2.1
# YouTube/Google Drive対応 + 単語レベル詳細分析 + SQLite履歴管理 + CSVエクスポート

import streamlit as st
import pandas as pd
import os
import json
import uuid
import sqlite3
import subprocess
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from openai import OpenAI
from pydub import AudioSegment
import io
import time

# ============================================
# 設定
# ============================================

DB_PATH = "history_speechace.db"
DOWNLOADS_DIR = Path("./downloads")
MAX_HISTORY = 1000
SPEECHACE_API_URL = "https://api2.speechace.com/api/scoring/text/v9/json"


def ensure_dir(d: Path):
    d.mkdir(parents=True, exist_ok=True)

# ============================================
# SQLite データベース管理
# ============================================

# クラス設定ファイル
CLASS_CONFIG_FILE = Path(__file__).parent / "class_config.json"

def load_config():
    """設定全体を読み込む"""
    if CLASS_CONFIG_FILE.exists():
        with open(CLASS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'university': '北海道大学',
        'department': '大学院メディア・コミュニケーション研究院',
        'classes': ['英語特定技能演習（発信）', '英語特定技能演習（受信）', '英語I', '英語II']
    }

def save_config(config):
    """設定全体を保存"""
    with open(CLASS_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_classes():
    """クラス設定を読み込む"""
    config = load_config()
    return config.get('classes', ['クラスA', 'クラスB'])

def save_classes(classes):
    """クラス設定を保存"""
    config = load_config()
    config['classes'] = classes
    save_config(config)

# クラスリスト
CLASS_LIST = ["-- 選択 --"] + load_classes()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id TEXT PRIMARY KEY,
            datetime TEXT,
            student_id TEXT NOT NULL,
            student_name TEXT,
            class_group TEXT,
            task_type TEXT,
            target_text TEXT,
            transcription TEXT,
            pronunciation REAL,
            fluency REAL,
            prosody REAL,
            total_score REAL,
            band TEXT,
            cefr TEXT,
            toefl TEXT,
            ielts TEXT,
            speechace_ielts TEXT,
            word_scores TEXT,
            problem_words TEXT,
            feedback TEXT,
            processing_time REAL
        )
    ''')
    conn.commit()
    conn.close()

def save_assessment(data: Dict[str, Any]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM assessments")
    count = c.fetchone()[0]
    if count >= MAX_HISTORY:
        c.execute(f"DELETE FROM assessments WHERE id IN (SELECT id FROM assessments ORDER BY datetime ASC LIMIT {count - MAX_HISTORY + 1})")
    
    c.execute('''
        INSERT INTO assessments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        str(uuid.uuid4())[:8],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data.get("student_id", ""),
        data.get("student_name", ""),
        data.get("class_group", ""),
        data.get("task_type", ""),
        data.get("target_text", "")[:500],
        data.get("transcription", "")[:1000],
        data.get("pronunciation", 0),
        data.get("fluency", 0),
        data.get("prosody", 0),
        data.get("total_score", 0),
        data.get("band", ""),
        data.get("cefr", ""),
        data.get("toefl", ""),
        data.get("ielts", ""),
        data.get("speechace_ielts", ""),
        data.get("word_scores", ""),
        data.get("problem_words", ""),
        data.get("feedback", ""),
        data.get("processing_time", 0)
    ))
    conn.commit()
    conn.close()

def get_all_history() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM assessments ORDER BY datetime DESC", conn)
    conn.close()
    return df

def get_student_history(student_id: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM assessments WHERE student_id = ? ORDER BY datetime DESC",
        conn, params=(student_id,)
    )
    conn.close()
    return df

def get_class_stats() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('''
        SELECT 
            class_group as クラス,
            COUNT(*) as 件数,
            ROUND(AVG(total_score), 1) as 平均点,
            ROUND(MIN(total_score), 1) as 最低点,
            ROUND(MAX(total_score), 1) as 最高点
        FROM assessments 
        WHERE class_group != '' AND class_group != '-- 選択 --'
        GROUP BY class_group ORDER BY class_group
    ''', conn)
    conn.close()
    return df

def export_csv() -> str:
    df = get_all_history()
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding='utf-8-sig')
    return buf.getvalue()

# ============================================
# 音声処理（YouTube / Google Drive / ファイル）
# ============================================

def convert_to_wav(input_path: Path, output_path: Path) -> Path:
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
    audio.export(output_path, format="wav")
    return output_path

def split_audio(audio_path: Path, max_seconds: int = 40) -> list:
    """音声を40秒ごとに分割"""
    audio = AudioSegment.from_file(audio_path)
    chunks = []
    chunk_ms = max_seconds * 1000
    
    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i + chunk_ms]
        chunk_path = DOWNLOADS_DIR / f"{uuid.uuid4().hex}_chunk{i//chunk_ms}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    
    return chunks

def download_from_youtube(url: str) -> Path:
    ensure_dir(DOWNLOADS_DIR)
    output_id = uuid.uuid4().hex
    output_template = str(DOWNLOADS_DIR / f"{output_id}.%(ext)s")
    
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "128K", "-o", output_template, "--no-playlist", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise ValueError(f"YouTube ダウンロードエラー: {result.stderr}")
    
    for f in DOWNLOADS_DIR.glob(f"{output_id}.*"):
        wav_path = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.wav"
        return convert_to_wav(f, wav_path)
    
    raise ValueError("ダウンロードしたファイルが見つかりません")

def download_from_google_drive(url: str) -> Path:
    ensure_dir(DOWNLOADS_DIR)
    
    try:
        import gdown
    except ImportError:
        raise ValueError("gdownがインストールされていません: pip install gdown")
    
    output_path = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.mp3"
    
    try:
        gdown.download(url, str(output_path), quiet=False, fuzzy=True)
    except Exception as e:
        raise ValueError(f"Google Drive ダウンロードエラー: {str(e)}")
    
    if not output_path.exists():
        raise ValueError("ダウンロードしたファイルが見つかりません")
    
    wav_path = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.wav"
    return convert_to_wav(output_path, wav_path)

def process_uploaded_file(uploaded_file) -> Path:
    ensure_dir(DOWNLOADS_DIR)
    ext = uploaded_file.name.split('.')[-1].lower()
    temp = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.{ext}"
    with open(temp, "wb") as f:
        f.write(uploaded_file.getvalue())
    wav = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.wav"
    return convert_to_wav(temp, wav)

# ============================================
# Speechace 発音評価
# ============================================

def speechace_assess_single(audio_path: Path, target_text: str, api_key: str) -> Dict[str, Any]:
    """単一チャンクの評価"""
    with open(audio_path, 'rb') as f:
        audio_data = f.read()
    
    files = {'user_audio_file': ('audio.wav', audio_data, 'audio/wav')}
    data = {
        'text': target_text,
        'question_info': '{"questionId": "q1"}',
        'user_id': 'student',
        'dialect': 'en-us',
        'include_fluency': '1',
        'include_intonation': '1'
    }
    params = {'key': api_key}
    
    response = requests.post(SPEECHACE_API_URL, params=params, files=files, data=data)
    
    if response.status_code != 200:
        raise ValueError(f"Speechace API エラー: {response.status_code}")
    
    return response.json()

def speechace_assess(audio_path: Path, target_text: str) -> Dict[str, Any]:
    api_key = os.getenv("SPEECHACE_API_KEY", "")
    if not api_key:
        raise ValueError("SPEECHACE_API_KEY が未設定です")
    
    # 音声を分割
    chunks = split_audio(audio_path, max_seconds=40)
    
    all_scores = []
    all_word_scores = []
    all_problem_words = []
    
    for chunk_path in chunks:
        try:
            result = speechace_assess_single(chunk_path, target_text, api_key)
            
            if result.get('status') == 'success':
                text_score = result.get('text_score', {})
                fluency_data = text_score.get('fluency', {})
                
                # segment_metrics_listから有効なセグメントのスコアを取得
                segment_list = fluency_data.get('segment_metrics_list', [])
                for seg in segment_list:
                    # durationが0のセグメントは無視（音声がない部分）
                    if seg.get('duration', 0) > 0:
                        seg_score = seg.get('speechace_score', {})
                        seg_ielts = seg.get('ielts_score', {})
                        if seg_score.get('pronunciation', 0) > 0:
                            all_scores.append({
                                'pronunciation': seg_score.get('pronunciation', 0),
                                'fluency': seg_score.get('fluency', 0),
                                'ielts_pron': seg_ielts.get('pronunciation', 0),
                                'ielts_fluency': seg_ielts.get('fluency', 0)
                            })
                
                # 単語スコアも取得
                for ws in text_score.get('word_score_list', []):
                    word = ws.get('word', '')
                    quality = ws.get('quality_score', 100)
                    all_word_scores.append(f"{word}:{quality}")
                    if quality < 70:
                        all_problem_words.append(f"{word}({quality}点)")
        except Exception as e:
            pass
    
    if not all_scores:
        raise ValueError("音声を評価できませんでした")
    
    # 有効なスコア（pronunciation >= 50）だけを抽出
    valid_scores = [s for s in all_scores if s['pronunciation'] >= 50]
    
    # 有効なスコアがない場合は全体から最高値を取得
    if not valid_scores:
        max_pron = max(s['pronunciation'] for s in all_scores)
        valid_scores = [s for s in all_scores if s['pronunciation'] == max_pron]
    
    # 有効セグメントの平均スコアを計算
    avg_pronunciation = sum(s['pronunciation'] for s in valid_scores) / len(valid_scores)
    avg_fluency = sum(s['fluency'] for s in valid_scores) / len(valid_scores)
    avg_ielts_pron = sum(s['ielts_pron'] for s in valid_scores) / len(valid_scores)
    avg_ielts_fluency = sum(s['ielts_fluency'] for s in valid_scores) / len(valid_scores)
    avg_ielts = (avg_ielts_pron + avg_ielts_fluency) / 2
    
    return {
        "transcription": target_text,
        "pronunciation": round(avg_pronunciation, 1),
        "fluency": round(avg_fluency, 1),
        "prosody": round((avg_pronunciation + avg_fluency) / 2, 1),  # 代替値
        "speechace_ielts": round(avg_ielts, 1) if avg_ielts else 'N/A',
        "word_scores": ", ".join(all_word_scores[:15]),
        "problem_words": ", ".join(all_problem_words[:10]) if all_problem_words else "特になし"
    }

def _old_speechace_assess(audio_path: Path, target_text: str) -> Dict[str, Any]:
    api_key = os.getenv("SPEECHACE_API_KEY", "")
    if not api_key:
        raise ValueError("SPEECHACE_API_KEY が未設定です")
    
    with open(audio_path, 'rb') as f:
        audio_data = f.read()
    
    files = {'user_audio_file': ('audio.wav', audio_data, 'audio/wav')}
    data = {
        'text': target_text,
        'question_info': '{"questionId": "q1"}',
        'user_id': 'student',
        'dialect': 'en-us',
        'include_fluency': '1',
        'include_intonation': '1'
    }
    params = {'key': api_key}
    
    response = requests.post(SPEECHACE_API_URL, params=params, files=files, data=data)
    
    if response.status_code != 200:
        raise ValueError(f"Speechace API エラー: {response.status_code}")
    
    result = response.json()
    
    if result.get('status') != 'success':
        raise ValueError(f"Speechace評価エラー: {result.get('detail_message', '不明')}")
    
    text_score = result.get('text_score', {})
    
    # 単語スコア解析
    word_scores = []
    problem_words = []
    
    for ws in text_score.get('word_score_list', []):
        word = ws.get('word', '')
        quality = ws.get('quality_score', 100)
        word_scores.append(f"{word}:{quality}")
        if quality < 70:
            problem_words.append(f"{word}({quality}点)")
    
    overall = text_score.get('speechace_score', {})
    fluency_data = text_score.get('fluency', {})
    
    return {
        "transcription": target_text,
        "pronunciation": round(overall.get('pronunciation', 0), 1),
        "fluency": round(fluency_data.get('overall_score', 0) if fluency_data else 0, 1),
        "prosody": round(fluency_data.get('rhythm_score', 0) if fluency_data else 0, 1),
        "speechace_ielts": overall.get('ielts_score', 'N/A'),
        "word_scores": ", ".join(word_scores[:10]),
        "problem_words": ", ".join(problem_words) if problem_words else "特になし"
    }

def whisper_transcribe(audio_path: Path) -> str:
    """Whisperで音声認識（目標テキストなしの場合）"""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY が必要です")
    
    client = OpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(model="whisper-1", file=f, language="en")
    return transcript.text

# ============================================
# スコア計算・換算
# ============================================

def calc_total(scores: Dict, task_type: str) -> float:
    if task_type == "reading":
        w = {"pronunciation": 0.50, "fluency": 0.30, "prosody": 0.20}
    else:
        w = {"pronunciation": 0.35, "fluency": 0.35, "prosody": 0.30}
    return round(scores["pronunciation"]*w["pronunciation"] + scores["fluency"]*w["fluency"] + scores["prosody"]*w["prosody"], 1)

def get_band(s: float) -> str:
    if s >= 85: return "A（優秀）"
    elif s >= 70: return "B（良好）"
    elif s >= 55: return "C（要努力）"
    else: return "D（要改善）"

def get_cefr(s: float) -> str:
    if s >= 90: return "C1"
    elif s >= 80: return "B2"
    elif s >= 70: return "B1"
    elif s >= 55: return "A2"
    elif s >= 40: return "A1"
    else: return "Pre-A1"

def get_toefl(s: float) -> str:
    if s >= 90: return f"{min(30, 26+int((s-90)/10*4))}/30"
    elif s >= 80: return f"{22+int((s-80)/10*4)}/30"
    elif s >= 70: return f"{18+int((s-70)/10*4)}/30"
    elif s >= 55: return f"{14+int((s-55)/15*4)}/30"
    else: return f"{max(0,int(s/55*14))}/30"

def get_ielts(s: float) -> str:
    if s >= 90: i = min(9.0, 8.0+(s-90)/10)
    elif s >= 80: i = 7.0+(s-80)/10
    elif s >= 70: i = 6.0+(s-70)/10
    elif s >= 60: i = 5.5+(s-60)/20
    elif s >= 50: i = 5.0+(s-50)/20
    elif s >= 40: i = 4.0+(s-40)/10
    else: i = max(1.0, s/40*4)
    return f"{round(i*2)/2}"

# ============================================
# AIフィードバック生成
# ============================================

def generate_feedback(transcription: str, target_text: str, scores: Dict, 
                      problem_words: str, task_type: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return "（OPENAI_API_KEY未設定のためフィードバック省略）"
    
    client = OpenAI(api_key=api_key)
    
    # 総合点を計算してレベル判定
    total = (scores['pronunciation'] + scores['fluency']) / 2
    
    if total >= 85:
        level_hint = "上位レベル。読んでる感をなくしスピーチのように。場数を踏む段階。"
    elif total >= 70:
        level_hint = "まあまあ良い方。リズム、抑揚、スピードの強弱を意識。"
    elif total >= 55:
        level_hint = "基本は掴んでいる。リズム、イントネーションを練習。"
    else:
        level_hint = "リズムを掴む練習が必要。発音より先にリズム、イントネーションを。"
    
    prompt = f"""あなたは日本の大学で英語を教える教員です。以下のサンプルのトーンを厳密に真似してフィードバックを書いてください。

【絶対禁止】
- 「素晴らしい！」「頑張ってください！」「この調子で！」のような過度に褒める表現
- 「！」の多用
- 学生を持ち上げすぎる表現

【サンプルコメント（このトーンを真似すること）】
1. 「もう少しリズムを掴む練習をしましょう。発音よりも、先ずはそこ。リズム、どこでポーズするか、スピードの強弱（単に速く読めって感じではない）、イントネーションを掴むといい。単語の発音も重要なんだけれど、日本語的でもそこが抑えられていれば、伝わる感じになる。」

2. 「なかなかいい方です。大幅に直すところは今のところないですが、次の段階にいきましょう。可能な範囲で読んでいる感をなくしていき、スピーチ原稿を確認しながら話しているような感じを目指して音読の練習をしてください。」

3. 「基本は掴んでいて、まあまあいい方だと思います。もう少しスピードの強弱をつけること、リズムを意識してください。余裕があるようであれば、単語レベルでの発音、特に子音の音を明瞭にすることも意識すると質の向上につながります。」

4. 「最初よりいいという気がしますが、つっかかてるところがあるので、そこはなるべく減らしていきましょう。」

5. 「伸び代があんまりでそうにないけれど、ここからのレベルは、場数を踏んで質をあげていくという感じなので、この調子で練習してください。」

【学生の評価データ】
- 目標テキスト: {target_text[:300]}
- 学生の発話: {transcription[:300]}
- 発音: {scores['pronunciation']}/100
- 流暢さ: {scores['fluency']}/100  
- 問題のある単語: {problem_words}
- レベル判定: {level_hint}

【フィードバックの構成】
1. 全体的な印象（サンプルのトーンで。「まあまあいい方」「もう少しリズムを」など率直に）
2. 良かった箇所があれば軽く触れる（大げさに褒めない）
3. 改善点：問題のある単語を具体的に指摘（「〜の発音に注意。/r/の音を意識して」など）
4. 練習のアドバイス（リズム、イントネーション、スピードの強弱、ポーズ位置など）

【条件】
- 300〜500字程度
- サンプルのトーンを厳守（率直、実践的、過度に褒めない、「！」を使わない）
- 「ですます調」と「だ・である調」混在OK"""
    
    try:
        res = client.chat.completions.create(
            model="gpt-4.1",
            temperature=0.7,
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"（フィードバック生成エラー: {str(e)}）"


# ============================================
# 評価実行（共通処理）
# ============================================

def run_assessment(audio_path: Path, student_id: str, student_name: str, 
                   class_group: str, task_type: str, task_name: str, target_text: str):
    
    start_time = time.time()
    # 目標テキストがない場合はWhisperで認識
    if not target_text:
        target_text = whisper_transcribe(audio_path)
    
    result = speechace_assess(audio_path, target_text)
    
    scores = {
        "pronunciation": result["pronunciation"],
        "fluency": result["fluency"],
        "prosody": result["prosody"]
    }
    # デバッグ表示
    st.write(f"DEBUG - 生スコア: pronunciation={result['pronunciation']}, fluency={result['fluency']}, prosody={result['prosody']}")
    task_val = "reading" if task_type == "音読課題" else "speech"
    total = calc_total(scores, task_val)
    band = get_band(total)
    cefr = get_cefr(total)
    toefl = get_toefl(total)
    ielts = get_ielts(total)
    
    feedback = generate_feedback(result["transcription"], target_text, scores, result["problem_words"], task_val)
    
    save_data = {
        "student_id": student_id,
        "student_name": student_name,
        "class_group": class_group if class_group != "-- 選択 --" else "",
        "task_type": task_type,
        "target_text": target_text,
        "transcription": target_text,
        "pronunciation": result["pronunciation"],
        "fluency": result["fluency"],
        "prosody": result["prosody"],
        "total_score": total,
        "band": band,
        "cefr": cefr,
        "toefl": toefl,
        "ielts": ielts,
        "speechace_ielts": str(result.get("speechace_ielts", "")),
        "word_scores": result["word_scores"],
        "problem_words": result["problem_words"],
        "feedback": feedback,
        "processing_time": round(time.time() - start_time, 1)
    }
    save_assessment(save_data)
    
    processing_time = round(time.time() - start_time, 1)
    st.success(f"✅ 評価完了！（処理時間: {processing_time}秒）履歴に保存しました。")
    
    st.divider()
    st.subheader("📊 評価結果")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総合スコア", f"{total}点")
    c2.metric("バンド", band.split("（")[0])
    c3.metric("CEFR", cefr)
    c4.metric("TOEFL Speaking", toefl)
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("発音スコア", f"{result['pronunciation']}")
    c2.metric("流暢さ", f"{result['fluency']}")
    c3.metric("プロソディ", f"{result['prosody']}")
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.info(f"**CEFR**: {cefr}")
    c2.info(f"**TOEFL Speaking**: {toefl}")
    c3.info(f"**IELTS Speaking**: {ielts}")
    
    if result.get("speechace_ielts") and result["speechace_ielts"] != "N/A":
        st.success(f"🎯 **Speechace IELTS推定スコア**: {result['speechace_ielts']}")
    
    st.divider()
    st.subheader("🔍 単語レベル分析")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**問題のある単語**")
        st.warning(result["problem_words"])
    with c2:
        st.markdown("**単語別スコア（一部）**")
        st.text(result["word_scores"])
    
    st.divider()
    with st.expander("📝 目標/認識テキスト", expanded=True):
        st.text(target_text)
    
    with st.expander("💬 AIフィードバック", expanded=True):
        st.write(feedback)

# ============================================
# Streamlit UI
# ============================================

st.set_page_config(page_title="英語評価 Speechace版 v2.1", page_icon="🎤", layout="wide")

init_db()

with st.sidebar:
    st.header("📊 メニュー")
    menu = st.radio("", ["🎯 評価実行", "📋 履歴一覧", "🔍 学生検索", "📈 クラス統計", "📥 CSV出力", "⚙️ クラス設定"])
    
    st.divider()
    
    # 操作ボタン
    st.subheader("🔧 操作")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 再読込", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("🚪 終了", use_container_width=True):
            st.warning("ターミナルを閉じてください")
            st.stop()
    
    st.divider()
    try:
        df = get_all_history()
        st.metric("総評価件数", len(df))
        if len(df) > 0:
            st.metric("全体平均", f"{df['total_score'].mean():.1f}点")
    except:
        st.info("履歴なし")

if menu == "🎯 評価実行":
    config = load_config()
    st.title("🎤 英語音読・スピーキング評価")
    st.caption(f"📍 {config.get('university', '')} {config.get('department', '')}")
    st.caption("Speechace API + GPT-4o | YouTube・Google Drive対応")
    
    with st.expander("ℹ️ Speechaceとは"):
        st.markdown("""
        - 発音評価に特化した専門API
        - IELTS/TOEFL/PTE公式基準に準拠
        - 単語ごとの詳細スコアを提供
        - Azure版と併用で客観性向上
        """)
    
    st.divider()
    
    st.subheader("👤 学生情報・課題")
    c1, c2 = st.columns(2)
    with c1:
        student_id = st.text_input("学籍番号 *", placeholder="例: 2024001")
    with c2:
        student_name = st.text_input("氏名（任意）", placeholder="例: 山田太郎")
    
    c1, c2 = st.columns(2)
    with c1:
        class_group = st.selectbox("クラス", CLASS_LIST)
    with c2:
        task_name = st.text_input("課題名", placeholder="例: 課題1、中間テスト等")
    
    st.divider()
    
    st.subheader("📝 課題設定")
    c1, c2 = st.columns([1, 2])
    with c1:
        task_type = st.radio("課題タイプ", ["音読課題", "スピーチ課題"], horizontal=True)
    with c2:
        if task_type == "音読課題":
            st.info("📖 発音精度重視（50%）- 目標テキスト必須")
        else:
            st.info("💬 総合評価 - 目標テキスト空欄可（Whisper認識）")
    
    target_text = st.text_area("目標テキスト", placeholder="音読課題は必須 / スピーチは空欄可", height=80)
    
    st.divider()
    
    st.subheader("🎵 音声入力")
    input_method = st.radio("入力方法", ["📁 ファイルアップロード", "🎬 YouTubeリンク", "📁 Google Driveリンク"], horizontal=True)
    
    if input_method == "📁 ファイルアップロード":
        uploaded = st.file_uploader("音声ファイル", type=["mp3", "wav", "m4a", "ogg", "webm"])
        
        if st.button("🚀 評価を実行", type="primary", use_container_width=True):
            if not student_id:
                st.error("⚠️ 学籍番号を入力してください")
            elif not uploaded:
                st.error("⚠️ 音声ファイルをアップロードしてください")
            elif False:  # 目標テキストなしでもOK
                st.error("⚠️ 音読課題では目標テキストが必須です")
            else:
                with st.spinner("🔄 評価中..."):
                    try:
                        audio_path = process_uploaded_file(uploaded)
                        run_assessment(audio_path, student_id, student_name, class_group, task_type, task_name, target_text)
                    except Exception as e:
                        st.error(f"❌ エラー: {str(e)}")
    
    elif input_method == "🎬 YouTubeリンク":
        youtube_url = st.text_input("YouTubeリンク", placeholder="https://www.youtube.com/watch?v=...")
        
        if st.button("🚀 評価を実行", type="primary", use_container_width=True):
            if not student_id:
                st.error("⚠️ 学籍番号を入力してください")
            elif not youtube_url:
                st.error("⚠️ YouTubeリンクを入力してください")
            elif False:  # 目標テキストなしでもOK
                st.error("⚠️ 音読課題では目標テキストが必須です")
            else:
                with st.spinner("🔄 YouTube音声をダウンロード中..."):
                    try:
                        audio_path = download_from_youtube(youtube_url)
                        st.success("✅ ダウンロード完了")
                    except Exception as e:
                        st.error(f"❌ ダウンロードエラー: {str(e)}")
                        st.stop()
                
                with st.spinner("🔄 評価中..."):
                    try:
                        run_assessment(audio_path, student_id, student_name, class_group, task_type, task_name, target_text)
                    except Exception as e:
                        st.error(f"❌ エラー: {str(e)}")
    
    elif input_method == "📁 Google Driveリンク":
        gdrive_url = st.text_input("Google Drive共有リンク", placeholder="https://drive.google.com/file/d/...")
        st.caption("※ 「リンクを知っている全員」に共有設定してください")
        
        if st.button("🚀 評価を実行", type="primary", use_container_width=True):
            if not student_id:
                st.error("⚠️ 学籍番号を入力してください")
            elif not gdrive_url:
                st.error("⚠️ Google Driveリンクを入力してください")
            elif False:  # 目標テキストなしでもOK
                st.error("⚠️ 音読課題では目標テキストが必須です")
            else:
                with st.spinner("🔄 Google Driveからダウンロード中..."):
                    try:
                        audio_path = download_from_google_drive(gdrive_url)
                        st.success("✅ ダウンロード完了")
                    except Exception as e:
                        st.error(f"❌ ダウンロードエラー: {str(e)}")
                        st.stop()
                
                with st.spinner("🔄 評価中..."):
                    try:
                        run_assessment(audio_path, student_id, student_name, class_group, task_type, task_name, target_text)
                    except Exception as e:
                        st.error(f"❌ エラー: {str(e)}")

elif menu == "📋 履歴一覧":
    st.title("📋 評価履歴一覧")
    df = get_all_history()
    if len(df) == 0:
        st.info("まだ履歴がありません")
    else:
        c1, c2 = st.columns(2)
        with c1:
            cls_filter = st.selectbox("クラス絞込", ["すべて"] + [c for c in CLASS_LIST if c != "-- 選択 --"])
        with c2:
            task_filter = st.selectbox("課題絞込", ["すべて", "音読課題", "スピーチ課題"])
        
        filtered = df.copy()
        if cls_filter != "すべて":
            filtered = filtered[filtered['class_group'] == cls_filter]
        if task_filter != "すべて":
            filtered = filtered[filtered['task_type'] == task_filter]
        
        st.caption(f"表示: {len(filtered)} / 全{len(df)}件")
        st.divider()
        
        # 各履歴を展開可能な形式で表示
        for _, row in filtered.iterrows():
            with st.expander(f"📝 {row['datetime']} | {row['student_id']} {row['student_name']} | {row['total_score']}点 | {row['band']}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("発音", f"{row['accuracy']}点")
                with col2:
                    st.metric("流暢さ", f"{row['fluency']}点")
                with col3:
                    st.metric("総合", f"{row['total_score']}点")
                
                st.write(f"**クラス:** {row['class_group']} | **課題タイプ:** {row['task_type']} | **課題名:** {row.get('task_name', '-')}")
                st.write(f"**CEFR:** {row['cefr']} | **TOEFL:** {row['toefl']} | **IELTS:** {row['ielts']}")
                
                if row.get('mispronounced_words'):
                    st.write(f"**誤発音:** {row['mispronounced_words']}")
                
                if row.get('feedback'):
                    st.divider()
                    st.write("**💬 AIフィードバック:**")
                    st.info(row['feedback'])

elif menu == "🔍 学生検索":
    st.title("🔍 学生別履歴検索")
    search_id = st.text_input("学籍番号を入力")
    if search_id:
        df = get_student_history(search_id)
        if len(df) == 0:
            st.warning("該当する履歴がありません")
        else:
            st.success(f"✅ {len(df)}件の履歴")
            c1, c2, c3 = st.columns(3)
            c1.metric("評価回数", len(df))
            c2.metric("平均点", f"{df['total_score'].mean():.1f}")
            c3.metric("最高点", f"{df['total_score'].max():.1f}")
            st.divider()
            for _, row in df.iterrows():
                with st.expander(f"📅 {row['datetime']} | {row['task_type']} | {row['total_score']}点"):
                    st.write(f"**発音**: {row['pronunciation']} / **流暢さ**: {row['fluency']} / **プロソディ**: {row['prosody']}")
                    st.write(f"**CEFR**: {row['cefr']} / **TOEFL**: {row['toefl']} / **IELTS**: {row['ielts']}")
                    st.write("**問題単語**:", row['problem_words'])
                    st.write("**フィードバック**:", row['feedback'])

elif menu == "📈 クラス統計":
    st.title("📈 クラス別統計")
    stats = get_class_stats()
    if len(stats) == 0:
        st.info("データがありません")
    else:
        st.dataframe(stats, use_container_width=True)
        import plotly.express as px
        fig = px.bar(stats, x='クラス', y='平均点', title='クラス別平均スコア', color='平均点', color_continuous_scale='Greens')
        st.plotly_chart(fig, use_container_width=True)

elif menu == "📥 CSV出力":
    st.title("📥 データエクスポート")
    df = get_all_history()
    if len(df) == 0:
        st.info("エクスポートするデータがありません")
    else:
        st.write(f"**エクスポート可能件数**: {len(df)}件")
        st.subheader("プレビュー（先頭10件）")
        st.dataframe(df.head(10), use_container_width=True)
        csv = export_csv()
        st.download_button("📥 CSVダウンロード", data=csv, file_name=f"speechace_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", use_container_width=True)

st.divider()
st.caption("Speechace API + GPT-4o | YouTube・Google Drive対応")
