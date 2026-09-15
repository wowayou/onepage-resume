/* 生成与导出：出 PDF / PNG / HTML，以及生成之后那几个链接。
 *
 * 生成物有哪些、叫什么名字由服务端 render.write_outputs() 说了算，这里只负责把
 * 返回的文件名列出来。"查看"只给能在浏览器沙箱里自己打开的（PDF、PNG）；
 * HTML 永远只给下载——内联打开等于让生成的页面脚本跑在本服务的源下。
 */

'use strict';

async function build() {
  if (el.render.disabled) return;
  const version = state.previewVersion;
  state.building = true;
  updateActions();
  try {
    const result = await api('/api/render', {
      method: 'POST',
      body: JSON.stringify({
        content: state.content,
        theme: el.theme.value,
      }),
    });
    if (version === state.previewVersion) {
      showDownloads(result.files);
      toast(`已生成到 ${result.out_dir}`, 'good');
    } else {
      toast('生成期间内容已变化，旧版本已生成；请为当前内容重新生成 PDF。');
    }
  } catch (error) {
    // 空白清单、超页这类错误可能是好几行，横幅能停住让你看完，toast 不行。
    banner(error.message);
  } finally {
    state.building = false;
    updateActions();
  }
}

// 能内联查看的类型：新标签页里交给浏览器自带的 PDF 阅读器 / 图片查看器。
// HTML 不给「查看」——内联打开等于让生成的页面脚本跑在本服务的源下。
const INLINE_KINDS = new Set(['pdf', 'png']);

function artifactUrl(name, inline) {
  const suffix = inline ? '&inline=1' : '';
  return `/api/artifact?name=${encodeURIComponent(name)}${suffix}`;
}

function showDownloads(files) {
  el.downloads.textContent = '';
  ['pdf', 'png', 'html'].forEach((kind) => {
    const name = files[kind];
    if (!name) return;
    if (INLINE_KINDS.has(kind)) {
      const view = node('a', null, `${kind.toUpperCase()} 查看`);
      view.href = artifactUrl(name, true);
      view.target = '_blank';
      view.rel = 'noopener';
      view.title = `在浏览器里打开 ${name}`;
      el.downloads.append(view);
    }
    const link = node('a', null, `${kind.toUpperCase()} 下载`);
    link.href = artifactUrl(name, false);
    link.title = `下载 ${name}`;
    el.downloads.append(link);
  });
}
