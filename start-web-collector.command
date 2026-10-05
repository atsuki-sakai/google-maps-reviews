#!/bin/zsh
set -eu
cd "${0:A:h}/web"

node_candidates=( "$HOME"/.nvm/versions/node/v22.*/bin/node(N) /opt/homebrew/bin/node /usr/local/bin/node )
node_path=""
for candidate in "${node_candidates[@]}"; do
  if [[ -x "$candidate" ]] && [[ "$("$candidate" -p 'process.versions.node.split(".")[0]')" == "22" ]]; then
    node_path="$candidate"
    break
  fi
done
if [[ -z "$node_path" ]]; then
  print 'Node.js 22をインストールしてから、もう一度起動してください。'
  read '?Enterで閉じます: '
  exit 1
fi
export PATH="${node_path:h}:$PATH"
if [[ ! -f node_modules/tsx/dist/cli.mjs ]]; then
  npm ci
fi
"$node_path" scripts/install-local-collector.mjs install
print '専用ChromeでGoogleマップを確認し、ログインを求められる場合はログインしてください。'
read '?Enterで閉じます（収集サービスは動作を続けます）: '
