#!/usr/bin/env python3
"""
Config.json 可视化管理器
启动后通过浏览器访问 http://<IP>:5000
"""

import json
import os
import sys
from flask import Flask, render_template_string, request, jsonify, send_file

app = Flask(__name__)

# 配置文件路径，默认与脚本同目录
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Config.json 可视化管理器</title>
<style>
  :root {
    --bg: #1a1a2e;
    --panel: #16213e;
    --border: #0f3460;
    --accent: #e94560;
    --text: #e0e0e0;
    --label: #a0a0b0;
    --input-bg: #1a1a2e;
    --btn-bg: #0f3460;
    --btn-hover: #1a4a7a;
    --danger: #c0392b;
    --danger-hover: #e74c3c;
    --success: #27ae60;
    --success-hover: #2ecc71;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; padding: 20px;
  }
  .container { max-width: 1100px; margin: 0 auto; }

  .toolbar {
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    margin-bottom: 20px; position: sticky; top: 10px; z-index: 100;
    background: var(--panel); padding: 15px; border-radius: 10px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }
  .toolbar button {
    padding: 10px 22px; border: none; border-radius: 6px;
    font-size: 14px; font-weight: 600; cursor: pointer;
    transition: all 0.2s; color: #fff; letter-spacing: 0.3px;
  }
  .btn-reload { background: #6c5ce7; }
  .btn-reload:hover { background: #7d6ff0; }
  .btn-save { background: var(--success); }
  .btn-save:hover { background: var(--success-hover); }
  .status {
    margin-left: auto; font-size: 13px; padding: 6px 14px;
    border-radius: 20px; background: #1a1a2e;
  }
  .status.ok { color: #2ecc71; }
  .status.err { color: #e74c3c; }

  .section {
    background: var(--panel); border-radius: 10px;
    margin-bottom: 20px; overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,0,0,0.2);
  }
  .section-header {
    padding: 16px 20px; background: var(--border);
    cursor: pointer; display: flex; align-items: center;
    justify-content: space-between; user-select: none;
    font-weight: 700; font-size: 15px;
  }
  .section-header:hover { background: #13315c; }
  .section-header .arrow { transition: transform 0.3s; font-size: 18px; }
  .section-header.collapsed .arrow { transform: rotate(-90deg); }
  .section-body { padding: 20px; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
  .section-body.collapsed { display: none; }
  .section-body.list-body { display: block; }

  .field { display: flex; flex-direction: column; gap: 5px; }
  .field label {
    font-size: 12px; color: var(--label); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.4px;
  }
  .field label .hint { font-weight: 400; text-transform: none; color: #707080; margin-left: 4px; }
  .field input, .field select {
    padding: 9px 12px; background: var(--input-bg);
    border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); font-size: 14px; outline: none;
  }
  .field input:focus, .field select:focus { border-color: var(--accent); }
  .field input[type="number"] { font-family: 'SF Mono', 'Consolas', monospace; }
  .field input[type="checkbox"] {
    width: 20px; height: 20px; cursor: pointer; accent-color: var(--accent);
  }

  .list-section { grid-column: 1 / -1; }
  .list-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 10px; flex-wrap: wrap; gap: 8px;
  }
  .list-header span { font-size: 13px; color: var(--label); font-weight: 600; }

  .list-item {
    display: flex; gap: 8px; align-items: center; margin-bottom: 8px;
    background: var(--bg); padding: 8px 10px; border-radius: 6px;
  }
  .list-item input {
    flex: 1; padding: 8px 10px; background: var(--input-bg);
    border: 1px solid var(--border); border-radius: 5px;
    color: var(--text); font-size: 13px; outline: none; min-width: 0;
  }
  .list-item input:focus { border-color: var(--accent); }
  .btn-del {
    padding: 6px 12px; background: var(--danger); color: #fff;
    border: none; border-radius: 5px; cursor: pointer; font-size: 12px;
    flex-shrink: 0;
  }
  .btn-del:hover { background: var(--danger-hover); }

  .correction-item {
    display: grid; grid-template-columns: 1fr 160px 160px 50px;
    gap: 8px; align-items: center; margin-bottom: 8px;
    background: var(--bg); padding: 10px; border-radius: 6px;
  }
  .correction-item input, .correction-item select {
    padding: 8px 10px; background: var(--input-bg);
    border: 1px solid var(--border); border-radius: 5px;
    color: var(--text); font-size: 13px; outline: none; min-width: 0;
  }
  .correction-item select { cursor: pointer; }
  .correction-item .value-field { display: none; }
  .correction-item.show-value .value-field { display: block; }
  .correction-item .btn-del { padding: 8px 0; text-align: center; }

  /* 添加按钮 - 右下角 */
  .list-footer {
    display: flex; justify-content: flex-end;
    margin-top: 14px; padding-top: 14px;
    border-top: 1px solid rgba(255,255,255,0.06);
  }
  .list-footer button {
    padding: 8px 20px; background: var(--btn-bg); color: #fff;
    border: none; border-radius: 5px; cursor: pointer; font-size: 13px;
    font-weight: 600; transition: background 0.2s;
  }
  .list-footer button:hover { background: var(--btn-hover); }

  .toast {
    position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
    background: var(--success); color: #fff; padding: 12px 28px;
    border-radius: 8px; font-weight: 600; z-index: 9999; pointer-events: none;
    animation: fadeInUp 0.3s ease;
  }
  .toast.error { background: var(--danger); }
  @keyframes fadeInUp {
    from { opacity: 0; transform: translateX(-50%) translateY(20px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  @media (max-width: 768px) {
    .section-body { grid-template-columns: 1fr; }
    .correction-item { grid-template-columns: 1fr 100px 80px 40px; }
  }
</style>
</head>
<body>
<div class="container">
  <div class="toolbar">
    <button class="btn-reload" onclick="loadConfig()">🔄 重新加载</button>
    <button class="btn-save" onclick="saveConfig()">💾 保存到服务器</button>
    <span class="status" id="status">加载中...</span>
  </div>
  <div id="app"></div>
</div>

<script>
let currentConfig = null;
let collapsedSections = {};

async function loadConfig() {
  try {
    const resp = await fetch('/api/config');
    const data = await resp.json();
    if (data.error) {
      setStatus('加载失败: ' + data.error, 'err');
      return;
    }
    currentConfig = data.config;
    setStatus('✅ 已加载 config.json', 'ok');
    render();
  } catch (e) {
    setStatus('❌ 无法连接服务器', 'err');
  }
}

async function saveConfig() {
  if (!currentConfig) {
    showToast('没有数据可保存', 'error');
    return;
  }
  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({config: currentConfig})
    });
    const data = await resp.json();
    if (data.success) {
      setStatus('✅ 已保存', 'ok');
      showToast('保存成功！');
    } else {
      setStatus('保存失败: ' + data.error, 'err');
      showToast('保存失败: ' + data.error, 'error');
    }
  } catch (e) {
    setStatus('❌ 保存失败', 'err');
    showToast('保存失败', 'error');
  }
}

function setStatus(msg, cls) {
  const s = document.getElementById('status');
  s.textContent = msg;
  s.className = 'status ' + (cls || '');
}

function showToast(msg, type) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const t = document.createElement('div');
  t.className = 'toast' + (type === 'error' ? ' error' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2000);
}

// ============ 渲染 ============
function render() {
  if (!currentConfig) return;
  const app = document.getElementById('app');
  let html = '';

  // 确保字段存在
  currentConfig.MAINLAND_CONFIG = currentConfig.MAINLAND_CONFIG || {};
  currentConfig.HKTW_CONFIG = currentConfig.HKTW_CONFIG || {};
  currentConfig.HK_TW_BRANDS = currentConfig.HK_TW_BRANDS || [];
  currentConfig.CONFIG_SOURCES = currentConfig.CONFIG_SOURCES || [];
  currentConfig.CORRECTION_DB = currentConfig.CORRECTION_DB || [];

  // 找出所有顶层对象/数组键
  const topKeys = Object.keys(currentConfig);

  for (const key of topKeys) {
    const val = currentConfig[key];
    if (Array.isArray(val)) {
      if (key === 'CORRECTION_DB') {
        html += renderCorrectionDB(key);
      } else {
        html += renderStringList(key);
      }
    } else if (typeof val === 'object' && val !== null) {
      html += renderObjectSection(key, Object.keys(val), val);
    }
  }

  app.innerHTML = html;

  // 恢复折叠
  Object.keys(collapsedSections).forEach(k => {
    if (collapsedSections[k]) {
      const h = document.querySelector(`[data-section="${CSS.escape(k)}"]`);
      if (h) h.classList.add('collapsed');
      const b = document.getElementById(`body-${CSS.escape(k)}`);
      if (b) b.classList.add('collapsed');
    }
  });
}

function renderObjectSection(key, fields, data) {
  const collapsed = collapsedSections[key] ? ' collapsed' : '';
  let fieldsHTML = '';
  fields.forEach(f => {
    const val = data[f];
    const type = typeof val;
    fieldsHTML += '<div class="field">';
    fieldsHTML += `<label>${fmtName(f)} <span class="hint">(${type})</span></label>`;
    if (type === 'boolean') {
      fieldsHTML += `<input type="checkbox" onchange="updateCheckbox('${esc(key)}','${esc(f)}',this)" ${val?'checked':''}>`;
    } else if (type === 'number') {
      const step = Number.isInteger(val) ? 1 : 0.5;
      fieldsHTML += `<input type="number" value="${val}" step="${step}" onchange="updateNumber('${esc(key)}','${esc(f)}',this)">`;
    } else {
      fieldsHTML += `<input type="text" value="${escHtml(String(val))}" onchange="updateString('${esc(key)}','${esc(f)}',this)">`;
    }
    fieldsHTML += '</div>';
  });
  return `
    <div class="section">
      <div class="section-header${collapsed}" data-section="${esc(key)}" onclick="toggleSection('${esc(key)}')">
        <span>📦 ${fmtName(key)} <small style="color:#a0a0b0;font-weight:400;">(${fields.length}个参数)</small></span>
        <span class="arrow">▼</span>
      </div>
      <div class="section-body${collapsed}" id="body-${esc(key)}">${fieldsHTML}</div>
    </div>`;
}

function renderStringList(key) {
  const collapsed = collapsedSections[key] ? ' collapsed' : '';
  const list = currentConfig[key] || [];
  let items = list.map((item, i) => `
    <div class="list-item">
      <input type="text" value="${escHtml(String(item))}" onchange="updateListItem('${esc(key)}',${i},this)">
      <button class="btn-del" onclick="deleteListItem('${esc(key)}',${i})">✕</button>
    </div>`).join('');
  return `
    <div class="section">
      <div class="section-header${collapsed}" data-section="${esc(key)}" onclick="toggleSection('${esc(key)}')">
        <span>📋 ${fmtName(key)} <small style="color:#a0a0b0;font-weight:400;">(${list.length}项)</small></span>
        <span class="arrow">▼</span>
      </div>
      <div class="section-body list-body${collapsed}" id="body-${esc(key)}">
        <div class="list-section">
          <div class="list-header">
            <span>共 ${list.length} 项</span>
          </div>
          ${items || '<p style="color:#707080;font-size:13px;">（空列表）</p>'}
          <div class="list-footer">
            <button onclick="addListItem('${esc(key)}')">+ 添加项</button>
          </div>
        </div>
      </div>
    </div>`;
}

function renderCorrectionDB(key) {
  const collapsed = collapsedSections[key] ? ' collapsed' : '';
  const list = currentConfig[key] || [];
  let items = list.map((rule, i) => {
    const isRename = rule.action === 'rename';
    return `
    <div class="correction-item ${isRename ? 'show-value' : ''}">
      <input type="text" value="${escHtml(rule.match||'')}" placeholder="匹配规则" onchange="updateCorrField(${i},'match',this)">
      <select onchange="updateCorrAction(${i},this)">
        <option value="discard" ${rule.action==='discard'?'selected':''}>discard</option>
        <option value="rename" ${rule.action==='rename'?'selected':''}>rename</option>
        ${!['discard','rename'].includes(rule.action) ? `<option value="${escHtml(rule.action)}" selected>${escHtml(rule.action)}</option>` : ''}
      </select>
      <input type="text" class="value-field" value="${escHtml(rule.value||'')}" placeholder="新名称" onchange="updateCorrField(${i},'value',this)">
      <button class="btn-del" onclick="deleteCorrItem(${i})">✕</button>
    </div>`;
  }).join('');
  return `
    <div class="section">
      <div class="section-header${collapsed}" data-section="${esc(key)}" onclick="toggleSection('${esc(key)}')">
        <span>🔧 ${fmtName(key)} <small style="color:#a0a0b0;font-weight:400;">(${list.length}条)</small></span>
        <span class="arrow">▼</span>
      </div>
      <div class="section-body list-body${collapsed}" id="body-${esc(key)}">
        <div class="list-section">
          <div class="list-header">
            <span>共 ${list.length} 条规则</span>
          </div>
          ${items || '<p style="color:#707080;font-size:13px;">（无规则）</p>'}
          <div class="list-footer">
            <button onclick="addCorrItem()">+ 添加规则</button>
          </div>
        </div>
      </div>
    </div>`;
}

// ============ 事件处理 ============
function toggleSection(key) {
  collapsedSections[key] = !collapsedSections[key];
  const h = document.querySelector(`[data-section="${CSS.escape(key)}"]`);
  const b = document.getElementById(`body-${CSS.escape(key)}`);
  if (h) h.classList.toggle('collapsed', collapsedSections[key]);
  if (b) b.classList.toggle('collapsed', collapsedSections[key]);
}

function updateNumber(section, key, input) {
  const raw = input.value.trim();
  if (raw === '') { currentConfig[section][key] = 0; return; }
  const oldVal = currentConfig[section][key];
  currentConfig[section][key] = Number.isInteger(oldVal) ? parseInt(raw,10) : parseFloat(raw);
}
function updateCheckbox(section, key, input) { currentConfig[section][key] = input.checked; }
function updateString(section, key, input) { currentConfig[section][key] = input.value; }
function updateListItem(section, idx, input) { currentConfig[section][idx] = input.value; }
function deleteListItem(section, idx) { currentConfig[section].splice(idx,1); render(); showToast('已删除'); }
function addListItem(section) { currentConfig[section].push(''); render(); showToast('已添加'); }
function updateCorrField(idx, field, input) { currentConfig['CORRECTION_DB'][idx][field] = input.value; }
function updateCorrAction(idx, select) {
  const action = select.value;
  currentConfig['CORRECTION_DB'][idx].action = action;
  if (action === 'rename') {
    if (!currentConfig['CORRECTION_DB'][idx].value) currentConfig['CORRECTION_DB'][idx].value = '';
  } else {
    delete currentConfig['CORRECTION_DB'][idx].value;
  }
  render();
}
function deleteCorrItem(idx) { currentConfig['CORRECTION_DB'].splice(idx,1); render(); showToast('已删除'); }
function addCorrItem() { currentConfig['CORRECTION_DB'].push({match:'',action:'discard'}); render(); showToast('已添加'); }

// ============ 工具 ============
function fmtName(key) { return key.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()); }
function escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function esc(s) { return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }

// 初始化
loadConfig();
</script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET':
        try:
            if not os.path.exists(CONFIG_PATH):
                return jsonify({'error': f'配置文件不存在: {CONFIG_PATH}'}), 404
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return jsonify({'config': config})
        except json.JSONDecodeError as e:
            return jsonify({'error': f'JSON 解析错误: {str(e)}'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data or 'config' not in data:
                return jsonify({'success': False, 'error': '无效的请求数据'}), 400
            
            config = data['config']
            
            # 备份原文件
            if os.path.exists(CONFIG_PATH):
                backup_path = CONFIG_PATH + '.bak'
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    original = f.read()
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(original)
            
            # 写入新配置
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    # 确保 config.json 存在
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️  警告: 配置文件不存在: {CONFIG_PATH}")
        print("   将创建一个空模板，请通过 Web 界面编辑")
        template = {
            "MAINLAND_CONFIG": {},
            "HKTW_CONFIG": {},
            "HK_TW_BRANDS": [],
            "CONFIG_SOURCES": [],
            "CORRECTION_DB": []
        }
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
    
    print(f"📁 配置文件: {CONFIG_PATH}")
    print(f"🌐 访问地址: http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)