#!/bin/bash

# Script to clear Python cache before deployment
# This helps prevent ImportError issues on Render

echo "🧹 Clearing Python cache..."

# Remove __pycache__ directories
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
echo "✅ Removed __pycache__ directories"

# Remove .pyc files
find . -name "*.pyc" -delete 2>/dev/null
echo "✅ Removed .pyc files"

# Remove .pyo files
find . -name "*.pyo" -delete 2>/dev/null
echo "✅ Removed .pyo files"

echo "🎉 Cache cleared successfully!"
