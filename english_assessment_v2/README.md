# 🎯 英語音読・スピーキング評価システム v2.0

2つの異なるエンジンで発音を評価し、客観性を高めるシステムです。

## 📁 ファイル構成

```
english_assessment_v2/
├── app_azure.py           # Azure Speech版アプリ
├── app_speechace.py       # Speechace版アプリ
├── Azure版を起動.command  # Azure版起動（Mac）
├── Speechace版を起動.command  # Speechace版起動（Mac）
├── requirements.txt       # 依存パッケージ
└── README.md             # このファイル
```

## 🔧 セットアップ手順

### 1. フォルダを配置
このフォルダを任意の場所に配置してください。

### 2. 仮想環境を作成（推奨）
```bash
cd english_assessment_v2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. APIキーを設定

#### Azure版（Azure版を起動.command を編集）
```bash
export AZURE_SPEECH_KEY="あなたのAzure Speech APIキー"
export AZURE_SPEECH_REGION="japaneast"
export OPENAI_API_KEY="あなたのOpenAI APIキー"
```

#### Speechace版（Speechace版を起動.command を編集）
```bash
export SPEECHACE_API_KEY="あなたのSpeechace APIキー"
export OPENAI_API_KEY="あなたのOpenAI APIキー"
```

### 4. 起動ファイルに実行権限を付与
```bash
chmod +x Azure版を起動.command
chmod +x Speechace版を起動.command
```

### 5. 起動
- **Azure版**: `Azure版を起動.command` をダブルクリック → http://localhost:8501
- **Speechace版**: `Speechace版を起動.command` をダブルクリック → http://localhost:8502

## 📊 2つのシステムの違い

| 項目 | Azure版 | Speechace版 |
|------|---------|-------------|
| エンジン | Microsoft Azure | Speechace |
| 音素分析 | ✅ 詳細（音素レベル） | ✅ 詳細（単語レベル） |
| 特徴 | 日本語対応、音素エラー検出 | IELTS/PTE公式基準 |
| ポート | 8501 | 8502 |
| 履歴DB | history_azure.db | history_speechace.db |

## 🎓 使い方

### 評価実行
1. 学籍番号を入力（必須）
2. クラスを選択
3. 課題タイプを選択（音読/スピーチ）
4. 目標テキストを入力（音読課題の場合）
5. 音声ファイルをアップロード
6. 「評価を実行」をクリック

### 履歴管理
- **履歴一覧**: 全評価履歴を表示・フィルター
- **学生検索**: 学籍番号で検索
- **クラス統計**: クラス別の集計・グラフ
- **CSV出力**: Excelで開けるCSV形式でダウンロード

## 📋 評価基準

### 総合スコア → バンド
| スコア | バンド | 説明 |
|--------|--------|------|
| 85-100 | A | 優秀 |
| 70-84 | B | 良好 |
| 55-69 | C | 要努力 |
| 0-54 | D | 要改善 |

### CEFR換算
| スコア | CEFR |
|--------|------|
| 90+ | C1 |
| 80-89 | B2 |
| 70-79 | B1 |
| 55-69 | A2 |
| 40-54 | A1 |
| 0-39 | Pre-A1 |

## 🔑 APIキー取得先

### Azure Speech Services
1. https://portal.azure.com にアクセス
2. 「Speech Services」を作成
3. 「キーとエンドポイント」からキーを取得
4. 無料枠: 5時間/月

### Speechace API
1. https://www.speechace.com/api/ にアクセス
2. アカウント作成・APIキー取得
3. 無料トライアルあり

### OpenAI API
1. https://platform.openai.com にアクセス
2. API Keysからキーを作成

## ⚠️ 注意事項

- **APIキーは絶対に公開しないでください**
- 履歴は各DBファイルに最大1000件保存されます
- 音声ファイルは `downloads/` フォルダに一時保存されます

## 🆘 トラブルシューティング

### 「音声を認識できませんでした」エラー
- 音声ファイルの音量を確認
- 英語以外の音声でないか確認
- 音声ファイルが破損していないか確認

### APIエラー
- APIキーが正しく設定されているか確認
- API利用上限に達していないか確認

---

© 2025 English Assessment System v2.0
