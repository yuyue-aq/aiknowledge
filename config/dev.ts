import type { UserConfigExport } from "@tarojs/cli"

export default {
  mini: {},
  h5: {
    router: {
      mode: 'hash',
      customRoutes: {
        '/pages/index/index': '/',
        '/pages/public/public': '/public'
      }
    }
  }
} satisfies UserConfigExport<'vite'>
