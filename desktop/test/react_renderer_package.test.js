const assert = require('assert');
const fs = require('fs');
const path = require('path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');

test('desktop package builds the React renderer with Vite', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.strictEqual(pkg.scripts['build:renderer'], 'vite build');
  assert.ok(pkg.dependencies.react);
  assert.ok(pkg.dependencies['react-dom']);
  assert.ok(pkg.devDependencies.vite);
  assert.ok(pkg.devDependencies['@vitejs/plugin-react']);
  assert.ok(pkg.build.files.includes('dist-renderer/**/*'));
});

test('Electron loads the built renderer with legacy fallback', () => {
  const windowSource = fs.readFileSync(path.join(root, 'src/main/window.js'), 'utf8');
  assert.match(windowSource, /dist-renderer\/index\.html/);
  assert.match(windowSource, /legacyIndex/);
});

test('main process store IPC is limited to known desktop settings', () => {
  const mainSource = fs.readFileSync(path.join(root, 'src/main/main.js'), 'utf8');
  assert.match(mainSource, /ALLOWED_STORE_KEYS/);
  assert.match(mainSource, /api_token_server_url/);
  assert.match(mainSource, /theme_mode/);
  assert.match(mainSource, /auto_sync/);
});
