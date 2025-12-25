# 🎯 English Pronunciation Assessment App

日本の大学向け英語発音・スピーキング評価アプリケーション

## ✨ 機能

- **音読課題評価**: Azure Speech APIによる音素レベルの詳細分析
- **スピーチ課題評価**: 発音・流暢さ・プロソディの総合評価
- **国際基準スコア**: CEFR / TOEFL / IELTS 換算
- **AIフィードバック**: GPT-4oによる教員スタイルのコメント生成
- **履歴管理**: SQLiteによる評価履歴保存・CSV出力
- **カスタマイズ**: 大学・クラス・課題名の設定

## 📦 2つのバージョン

| バージョン | エンジン | 特徴 |
|-----------|----------|------|
| Azure版 (`app_azure.py`) | Azure Speech | 音素レベル詳細分析、長時間音声対応 |
| Speechace版 (`app_speechace.py`) | Speechace API | IELTS/TOEFL公式基準、単語別スコア |

## 🚀 セットアップ

### 1. 必要なもの

- Python 3.9以上
- Azure Speech APIキー
- OpenAI APIキー
- Speechace APIキー（オプション）

### 2. インストール
```bash
git clone https://github.com/YOUR_USERNAME/english-assessment.git
cd english-assessment

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 環境変数の設定
```bash
cp .env.example .env
# .envファイルを編集してAPIキーを設定
```

### 4. 起動
```bash
# Azure版
streamlit run app_azure.py --server.port 8501

# Speechace版
streamlit run app_speechace.py --server.port 8502
```

ブラウザで http://localhost:8501 にアクセス

## 📖 使い方

1. 学生情報（学籍番号、氏名、クラス、課題名）を入力
2. 課題タイプ（音読/スピーチ）を選択
3. 音声ファイルをアップロード
4. 「評価を実行」をクリック
5. 結果とAIフィードバックを確認

## ⚙️ カスタマイズ

`class_config.json`で大学名・クラス・課題名を設定：
```json
{
  "university": "○○大学",
  "department": "○○学部",
  "classes": ["英語I", "英語II"],
  "tasks": ["課題1", "課題2"]
}
```

## 📝 ライセンス

MIT License

## 👤 開発者

北海道大学 大学院メディア・コミュニケーション研究院
