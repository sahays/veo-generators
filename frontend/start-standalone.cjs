const http = require('http')
const net = require('net')

const FASTAPI_HOST = process.env.FASTAPI_INTERNAL_HOST || '127.0.0.1'
const FASTAPI_PORT = parseInt(process.env.FASTAPI_INTERNAL_PORT || '8000', 10)

const origCreateServer = http.createServer

http.createServer = function patchedCreateServer(...args) {
  const nextListener = typeof args[args.length - 1] === 'function' ? args.pop() : null
  const server = origCreateServer.apply(this, args)

  if (nextListener) {
    server.on('request', (req, res) => {
      if (req.url === '/health' || req.url?.startsWith('/health?')) {
        const proxyReq = http.get(
          {
            hostname: FASTAPI_HOST,
            port: FASTAPI_PORT,
            path: req.url,
          },
          (proxyRes) => {
            res.writeHead(proxyRes.statusCode || 200, {
              'Content-Type': proxyRes.headers['content-type'] || 'application/json',
            })
            proxyRes.pipe(res)
          },
        )
        proxyReq.on('error', (err) => {
          console.error('Health check proxy error:', err.message)
          if (!res.headersSent) res.writeHead(502)
          res.end('Bad Gateway')
        })
        return
      }
      nextListener(req, res)
    })
  }

  server.on('upgrade', (req, socket, head) => {
    if (!req.url?.startsWith('/api/v1/')) {
      return
    }
    const upstream = net.connect(FASTAPI_PORT, FASTAPI_HOST, () => {
      const headerLines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`]
      for (let i = 0; i < req.rawHeaders.length; i += 2) {
        headerLines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`)
      }
      headerLines.push('', '')
      upstream.write(headerLines.join('\r\n'))
      if (head && head.length > 0) {
        upstream.write(head)
      }
      socket.pipe(upstream).pipe(socket)
    })

    const closeBoth = () => {
      socket.destroy()
      upstream.destroy()
    }
    upstream.on('error', closeBoth)
    socket.on('error', closeBoth)
  })

  return server
}

require('./server.js')
