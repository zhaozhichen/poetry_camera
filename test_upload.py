#!/usr/bin/env python3
"""
测试上传功能的调试脚本
运行: python3 test_upload.py
"""

import os
import sys
import base64
import requests
from pathlib import Path

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 手动解析 .env
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

# 读取配置
WEB_APP_URL = os.getenv('WEB_APP_URL', 'https://poetry.ktizo.io')
WEB_APP_API_KEY = os.getenv('WEB_APP_API_KEY')

# 回退到文件
if not WEB_APP_API_KEY:
    api_key_file = Path(__file__).parent / '.web_app_api_key'
    if api_key_file.exists():
        with open(api_key_file, 'r') as f:
            WEB_APP_API_KEY = f.readline().strip()

print("=== 上传功能测试 ===\n")

print(f"1. Web App URL: {WEB_APP_URL}")
print(f"2. API Key 配置状态: {'已配置' if WEB_APP_API_KEY else '未配置'}")

if WEB_APP_API_KEY:
    # 显示 API Key 的前后几个字符（用于验证，不显示完整密钥）
    key_len = len(WEB_APP_API_KEY)
    if key_len > 10:
        masked_key = WEB_APP_API_KEY[:4] + "..." + WEB_APP_API_KEY[-4:]
    else:
        masked_key = "***"  # 太短，不显示
    print(f"   API Key 长度: {key_len} 字符")
    print(f"   API Key 预览: {masked_key}")
    
    # 检查是否有空格或换行符
    if WEB_APP_API_KEY != WEB_APP_API_KEY.strip():
        print("   ⚠️  警告: API Key 包含前导或尾随空格/换行符")
        print(f"   原始长度: {len(WEB_APP_API_KEY)}")
        print(f"   去除空格后长度: {len(WEB_APP_API_KEY.strip())}")
        WEB_APP_API_KEY = WEB_APP_API_KEY.strip()
else:
    print("   ❌ 错误: 未找到 WEB_APP_API_KEY")
    print("   请检查 .env 文件或 .web_app_api_key 文件")
    sys.exit(1)

print("\n3. 测试网络连接:")
try:
    response = requests.get(f"{WEB_APP_URL}/api/poems", timeout=10)
    print(f"   ✓ 可以连接到 Web 应用 (HTTP {response.status_code})")
except requests.exceptions.ConnectionError:
    print(f"   ✗ 无法连接到 {WEB_APP_URL}")
    print("   请检查网络连接和 URL 是否正确")
    sys.exit(1)
except Exception as e:
    print(f"   ✗ 连接错误: {e}")
    sys.exit(1)

print("\n4. 测试 API 认证:")
# 创建一个小的测试图片
test_image_data = base64.b64encode(b"fake_image_data_for_test").decode('utf-8')

headers = {
    "X-API-Key": WEB_APP_API_KEY,
    "Content-Type": "application/json"
}

payload = {
    "poem": "测试诗歌",
    "image": test_image_data
}

print(f"   发送测试请求到: {WEB_APP_URL}/api/upload")
print(f"   请求头 X-API-Key: {WEB_APP_API_KEY[:8]}...{WEB_APP_API_KEY[-8:]}")

try:
    response = requests.post(
        f"{WEB_APP_URL}/api/upload",
        json=payload,
        headers=headers,
        timeout=30
    )
    
    print(f"   响应状态码: {response.status_code}")
    print(f"   响应内容: {response.text[:200]}")
    
    if response.status_code == 201:
        print("   ✓ 认证成功！API Key 正确")
    elif response.status_code == 401:
        print("   ✗ 认证失败 (401 Unauthorized)")
        print("   可能的原因:")
        print("   - API Key 不正确")
        print("   - API Key 包含额外的空格或换行符")
        print("   - Web 应用端的 POETRY_API_KEY 环境变量未设置或不同")
        print("\n   建议:")
        print("   1. 检查 .env 文件中的 WEB_APP_API_KEY")
        print("   2. 确保 Web 应用端的 .env 文件中的 POETRY_API_KEY 与此相同")
        print("   3. 检查 API Key 是否有空格: echo -n 'YOUR_KEY' | wc -c")
    else:
        print(f"   ⚠️  其他错误: {response.status_code}")
        
except Exception as e:
    print(f"   ✗ 请求失败: {e}")

print("\n=== 测试完成 ===")

