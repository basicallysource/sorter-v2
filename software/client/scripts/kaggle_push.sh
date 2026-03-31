#!/usr/bin/env bash
# Push dataset and notebook to Kaggle, then monitor
set -euo pipefail

CLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
KAGGLE_DIR="$CLIENT_DIR/blob/kaggle_dataset"
NOTEBOOK_DIR="$CLIENT_DIR/blob/kaggle_notebook"

# Get Kaggle username
KAGGLE_USER=$(python3 -c "import json; print(json.load(open('$HOME/.kaggle/kaggle.json'))['username'])")
echo "Kaggle user: $KAGGLE_USER"

# Fix dataset metadata with actual username
sed -i '' "s/INSERT_USERNAME/$KAGGLE_USER/" "$KAGGLE_DIR/dataset-metadata.json"

# Step 1: Upload dataset
echo "=== Uploading dataset ==="
kaggle datasets create -p "$KAGGLE_DIR" --dir-mode zip

# Step 2: Prepare notebook
mkdir -p "$NOTEBOOK_DIR"
cp "$CLIENT_DIR/scripts/kaggle_nanodet_notebook.ipynb" "$NOTEBOOK_DIR/kaggle_nanodet_notebook.ipynb"

# Create kernel metadata
cat > "$NOTEBOOK_DIR/kernel-metadata.json" << EOF
{
  "id": "$KAGGLE_USER/lego-nanodet-training",
  "title": "LEGO NanoDet Training",
  "code_file": "kaggle_nanodet_notebook.ipynb",
  "language": "python",
  "kernel_type": "notebook",
  "is_private": true,
  "enable_gpu": true,
  "enable_internet": true,
  "dataset_sources": ["$KAGGLE_USER/lego-chamber-detection"],
  "competition_sources": [],
  "kernel_sources": []
}
EOF

# Step 3: Push notebook
echo "=== Pushing notebook ==="
kaggle kernels push -p "$NOTEBOOK_DIR"

echo ""
echo "=== Done! ==="
echo "Monitor: kaggle kernels status $KAGGLE_USER/lego-nanodet-training"
echo "Output:  kaggle kernels output $KAGGLE_USER/lego-nanodet-training -p blob/kaggle_results/"
