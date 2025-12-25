# app_azure.py - Azure Speech版 パワーアップ版 v2.1
# YouTube/Google Drive対応 + 音素レベル詳細分析 + SQLite履歴管理 + CSVエクスポート

import streamlit as st
import pandas as pd
import os
import json
import uuid
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import azure.cognitiveservices.speech as speechsdk
from openai import OpenAI
from pydub import AudioSegment
import io
import time

# ============================================
# 設定
# ============================================

DB_PATH = "history_azure.db"
DOWNLOADS_DIR = Path("./downloads")
MAX_HISTORY = 1000

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

def load_tasks():
    """課題名設定を読み込む"""
    config = load_config()
    return config.get('tasks', ['課題1', '課題2', '課題3'])

def save_tasks(tasks):
    """課題名設定を保存"""
    config = load_config()
    config['tasks'] = tasks
    save_config(config)

# クラス・課題リスト
CLASS_LIST = ["-- 選択 --"] + load_classes()
TASK_LIST = ["-- 選択 --"] + load_tasks()

def save_classes(classes):
    """クラス設定を保存"""
    config = load_config()
    config['classes'] = classes
    save_config(config)

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
            accuracy REAL,
            fluency REAL,
            prosody REAL,
            completeness REAL,
            total_score REAL,
            band TEXT,
            cefr TEXT,
            toefl TEXT,
            ielts TEXT,
            mispronounced_words TEXT,
            phoneme_errors TEXT,
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
        data.get("accuracy", 0),
        data.get("fluency", 0),
        data.get("prosody", 0),
        data.get("completeness", 0),
        data.get("total_score", 0),
        data.get("band", ""),
        data.get("cefr", ""),
        data.get("toefl", ""),
        data.get("ielts", ""),
        data.get("mispronounced_words", ""),
        data.get("phoneme_errors", ""),
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

def download_from_youtube(url: str) -> Path:
    """YouTubeから音声をダウンロード"""
    ensure_dir(DOWNLOADS_DIR)
    output_id = uuid.uuid4().hex
    output_template = str(DOWNLOADS_DIR / f"{output_id}.%(ext)s")
    
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "128K",
        "-o", output_template,
        "--no-playlist",
        url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise ValueError(f"YouTube ダウンロードエラー: {result.stderr}")
    
    # ダウンロードされたファイルを探す
    for f in DOWNLOADS_DIR.glob(f"{output_id}.*"):
        wav_path = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.wav"
        return convert_to_wav(f, wav_path)
    
    raise ValueError("ダウンロードしたファイルが見つかりません")

def download_from_google_drive(url: str) -> Path:
    """Google Driveから音声をダウンロード"""
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
    """アップロードされたファイルを処理"""
    ensure_dir(DOWNLOADS_DIR)
    ext = uploaded_file.name.split('.')[-1].lower()
    temp = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.{ext}"
    with open(temp, "wb") as f:
        f.write(uploaded_file.getvalue())
    wav = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.wav"
    return convert_to_wav(temp, wav)

# ============================================
# Azure Speech 発音評価
# ============================================

def azure_assess(audio_path: Path, target_text: Optional[str] = None) -> Dict[str, Any]:
    region = os.getenv("AZURE_SPEECH_REGION", "")
    key = os.getenv("AZURE_SPEECH_KEY", "")
    
    if not region or not key:
        raise ValueError("AZURE_SPEECH_REGION / AZURE_SPEECH_KEY が未設定")
    
    speech_cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    audio_cfg = speechsdk.audio.AudioConfig(filename=str(audio_path))
    
    if not target_text:
        rec = speechsdk.SpeechRecognizer(speech_config=speech_cfg, language="en-US", audio_config=audio_cfg)
        res = rec.recognize_once()
        if res.reason == speechsdk.ResultReason.NoMatch:
            raise ValueError("音声を認識できませんでした")
        target_text = res.text
        audio_cfg = speechsdk.audio.AudioConfig(filename=str(audio_path))
    
    pron_cfg = speechsdk.PronunciationAssessmentConfig(
        reference_text=target_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
        enable_miscue=True
    )
    pron_cfg.enable_prosody_assessment()
    
    rec = speechsdk.SpeechRecognizer(speech_config=speech_cfg, language="en-US", audio_config=audio_cfg)
    pron_cfg.apply_to(rec)
    res = rec.recognize_once()
    
    if res.reason == speechsdk.ResultReason.NoMatch:
        raise ValueError("音声を認識できませんでした")
    
    pron = speechsdk.PronunciationAssessmentResult(res)
    raw = json.loads(res.properties.get(speechsdk.PropertyId.SpeechServiceResponse_JsonResult))
    
    mispronounced, phoneme_err = analyze_errors(raw)
    
    return {
        "transcription": res.text,
        "accuracy": round(pron.accuracy_score, 1),
        "fluency": round(pron.fluency_score, 1),
        "prosody": round(pron.prosody_score, 1),
        "completeness": round(pron.completeness_score, 1),
        "mispronounced_words": mispronounced,
        "phoneme_errors": phoneme_err,
        "raw": raw
    }

def analyze_errors(raw: Dict) -> tuple:
    mispronounced = []
    phoneme_errs = []
    
    try:
        words = raw.get("NBest", [{}])[0].get("Words", [])
        for w in words:
            word = w.get("Word", "")
            acc = w.get("PronunciationAssessment", {}).get("AccuracyScore", 100)
            err = w.get("PronunciationAssessment", {}).get("ErrorType", "None")
            
            if acc < 80 or err != "None":
                err_label = {"Omission": "省略", "Insertion": "挿入", "Mispronunciation": "誤発音"}.get(err, "")
                mispronounced.append(f"{word}({int(acc)}点{err_label})")
            
            for ph in w.get("Phonemes", []):
                ph_acc = ph.get("PronunciationAssessment", {}).get("AccuracyScore", 100)
                if ph_acc < 60:
                    phoneme_errs.append(f"/{ph.get('Phoneme', '')}/({word}内, {int(ph_acc)}点)")
    except:
        pass
    
    return (", ".join(mispronounced) if mispronounced else "特になし",
            ", ".join(phoneme_errs[:5]) if phoneme_errs else "特になし")

# ============================================
# スコア計算・換算
# ============================================

def calc_total(scores: Dict, task_type: str) -> float:
    if task_type == "reading":
        w = {"accuracy": 0.50, "fluency": 0.25, "prosody": 0.15, "completeness": 0.10}
    else:
        w = {"accuracy": 0.30, "fluency": 0.30, "prosody": 0.20, "completeness": 0.20}
    return round(scores["accuracy"]*w["accuracy"] + scores["fluency"]*w["fluency"] + 
                 scores["prosody"]*w["prosody"] + scores["completeness"]*w["completeness"], 1)

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
                      mispronounced: str, phoneme_errors: str, task_type: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return "（OPENAI_API_KEY未設定のためフィードバック省略）"
    
    client = OpenAI(api_key=api_key)
    
    # 総合点を計算してレベル判定
    if task_type == "reading":
        total = scores['accuracy']*0.5 + scores['fluency']*0.3 + scores['prosody']*0.2
    else:
        total = scores['accuracy']*0.3 + scores['fluency']*0.35 + scores['prosody']*0.35
    
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
- 発音精度: {scores['accuracy']}/100
- 流暢さ: {scores['fluency']}/100  
- プロソディ: {scores['prosody']}/100
- 誤発音単語: {mispronounced}
- 音素エラー: {phoneme_errors}
- レベル判定: {level_hint}

【フィードバックの構成】
1. 全体的な印象（サンプルのトーンで。「まあまあいい方」「もう少しリズムを」など率直に）
2. 良かった箇所があれば軽く触れる（大げさに褒めない）
3. 改善点：誤発音単語や音素エラーを具体的に指摘（「〜の発音に注意。/r/の音を意識して」など）
4. 練習のアドバイス（リズム、イントネーション、スピードの強弱、ポーズ位置など）

【条件】
- 300〜500字程度
- サンプルのトーンを厳守（率直、実践的、過度に褒めない、「！」を使わない）
- 「ですます調」と「だ・である調」混在OK"""
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
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
    result = azure_assess(audio_path, target_text if target_text else None)
    
    scores = {
        "accuracy": result["accuracy"],
        "fluency": result["fluency"],
        "prosody": result["prosody"],
        "completeness": result["completeness"]
    }
    task_val = "reading" if task_type == "音読課題" else "speech"
    total = calc_total(scores, task_val)
    band = get_band(total)
    cefr = get_cefr(total)
    toefl = get_toefl(total)
    ielts = get_ielts(total)
    
    feedback = generate_feedback(
        result["transcription"], target_text or result["transcription"],
        scores, result["mispronounced_words"], result["phoneme_errors"], task_val
    )
    
    save_data = {
        "student_id": student_id,
        "student_name": student_name,
        "class_group": class_group if class_group != "-- 選択 --" else "",
        "task_type": task_type,
        "target_text": target_text,
        "transcription": result["transcription"],
        "accuracy": result["accuracy"],
        "fluency": result["fluency"],
        "prosody": result["prosody"],
        "completeness": result["completeness"],
        "total_score": total,
        "band": band,
        "cefr": cefr,
        "toefl": toefl,
        "ielts": ielts,
        "mispronounced_words": result["mispronounced_words"],
        "phoneme_errors": result["phoneme_errors"],
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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("発音精度", f"{result['accuracy']}")
    c2.metric("流暢さ", f"{result['fluency']}")
    c3.metric("プロソディ", f"{result['prosody']}")
    c4.metric("完全性", f"{result['completeness']}")
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.info(f"**CEFR**: {cefr}")
    c2.info(f"**TOEFL Speaking**: {toefl}")
    c3.info(f"**IELTS Speaking**: {ielts}")
    
    st.divider()
    st.subheader("🔍 音素レベル分析")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**誤発音・問題のある単語**")
        st.warning(result["mispronounced_words"])
    with c2:
        st.markdown("**音素レベルのエラー**")
        st.warning(result["phoneme_errors"])
    
    st.divider()
    with st.expander("📝 書き起こしテキスト", expanded=True):
        st.text(result["transcription"])
    
    with st.expander("💬 AIフィードバック", expanded=True):
        st.write(feedback)

# ============================================
# Streamlit UI
# ============================================

st.set_page_config(page_title="英語評価 Azure版 v2.1", page_icon="🎯", layout="wide")

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
    st.title("🎯 英語音読・スピーキング評価")
    st.caption(f"📍 {config.get('university', '')} {config.get('department', '')}")
    st.caption("Azure Speech + GPT-4o | YouTube・Google Drive対応")
    
    with st.expander("ℹ️ このシステムについて"):
        st.markdown("""
        **入力方法**
        - 📁 ファイルアップロード（MP3, WAV, M4A等）
        - 🎬 YouTubeリンク（限定公開OK）
        - 📁 Google Driveリンク（共有リンク）
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
            st.info("📖 発音精度重視（50%）")
        else:
            st.info("💬 総合評価")
    
    target_text = st.text_area("目標テキスト（音読課題の場合）", placeholder="スピーチ課題は空欄可", height=80)
    
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
            feedback_preview = str(row.get('feedback', ''))[:50] + "..." if len(str(row.get('feedback', ''))) > 50 else str(row.get('feedback', ''))
            task_name_display = row.get('task_name', '') or ''
            with st.expander(f"📝 {row['datetime']} | {row['student_id']} {row['student_name']} | {task_name_display} | {row['total_score']}点"):
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
                    st.write(f"**発音**: {row['accuracy']} / **流暢さ**: {row['fluency']} / **プロソディ**: {row['prosody']}")
                    st.write(f"**CEFR**: {row['cefr']} / **TOEFL**: {row['toefl']} / **IELTS**: {row['ielts']}")
                    st.write("**誤発音**:", row['mispronounced_words'])
                    st.write("**フィードバック**:", row['feedback'])

elif menu == "📈 クラス統計":
    st.title("📈 クラス別統計")
    stats = get_class_stats()
    if len(stats) == 0:
        st.info("データがありません")
    else:
        st.dataframe(stats, use_container_width=True)
        import plotly.express as px
        fig = px.bar(stats, x='クラス', y='平均点', title='クラス別平均スコア', color='平均点', color_continuous_scale='Blues')
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
        st.download_button("📥 CSVダウンロード", data=csv, file_name=f"azure_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", use_container_width=True)

st.divider()
st.caption("Azure Speech + GPT-4o | YouTube・Google Drive対応")
