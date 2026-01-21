// 页面加载完成后立即执行
document.addEventListener('DOMContentLoaded', async () => {
  const statusDiv = document.getElementById('status');
  
  try {
    // 1. 获取当前标签页
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    
    try {
      // 2. 获取页面文本 - 使用 Manifest V3 的 scripting API
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          return document.body.innerText || document.body.textContent;
        }
      });
      
      const pageText = results[0].result;
      
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
    }
    
  } catch (error) {
    console.error('获取标签页失败:', error);
    statusDiv.textContent = `✗ 获取标签页失败: ${error.message}`;
    statusDiv.className = 'error';
  }
});