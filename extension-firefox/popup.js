// 页面加载完成后立即执行
document.addEventListener('DOMContentLoaded', async () => {
  const statusDiv = document.getElementById('status');
  
  try {
    // 1. 获取当前标签页
    const [tab] = await browser.tabs.query({active: true, currentWindow: true});
    
    // 2. 获取页面文本
    const result = await browser.tabs.executeScript(tab.id, {
      code: `document.body.innerText || document.body.textContent`
    });
    
    const pageText = result[0];
    
    // 3. 使用表单格式发送
    const formData = new URLSearchParams();
    formData.append('title', tab.title);
    formData.append('url', tab.url);
    formData.append('text', pageText);
    
    // 4. 发送请求
    const response = await fetch('http://localhost:24981/receive', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: formData.toString()
    });
    
    // 5. 显示结果
    if (response.ok) {
      statusDiv.textContent = '✓ 发送成功';
      statusDiv.className = 'success';
      
      // 2秒后自动关闭弹窗（可选）
      setTimeout(() => {
        window.close();
      }, 2000);
      
    } else {
      throw new Error(`HTTP ${response.status}`);
    }
    
  } catch (error) {
    console.error('发送失败:', error);
    statusDiv.textContent = `✗ 失败: ${error.message}`;
    statusDiv.className = 'error';
    
    // 错误时不自动关闭，让用户看到错误信息
  }
});