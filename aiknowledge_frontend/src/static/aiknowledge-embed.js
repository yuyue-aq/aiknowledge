(function (global) {
  'use strict';

  function mount(options) {
    options = options || {};
    if (!options.token || !options.target) {
      throw new Error('AiKnowledgeEmbed.mount requires token and target');
    }
    var target = typeof options.target === 'string'
      ? document.querySelector(options.target)
      : options.target;
    if (!target) {
      throw new Error('AiKnowledgeEmbed target was not found');
    }
    var publicUrl = String(options.publicUrl || '').replace(/\/$/, '');
    if (!publicUrl) {
      throw new Error('AiKnowledgeEmbed.mount requires publicUrl');
    }
    var iframe = document.createElement('iframe');
    iframe.title = options.title || '知洲知识问答';
    iframe.loading = 'lazy';
    iframe.referrerPolicy = 'no-referrer';
    iframe.style.width = '100%';
    iframe.style.height = options.height || '560px';
    iframe.style.border = '0';
    iframe.src = publicUrl + '/public/embed?token=' + encodeURIComponent(options.token);
    target.innerHTML = '';
    target.appendChild(iframe);
    return iframe;
  }

  global.AiKnowledgeEmbed = { mount: mount };
}(window));
