const http = require('http')
const net = require('net')

const FASTAPI_HOST = process.env.FASTAPI_INTERNAL_HOST || '127.0.0.1'
const FASTAPI_PORT = parseInt(process.env.FASTAPI_INTERNAL_PORT || '8000', 10)

const origCreateServer = http.createServer

http.createServer = function patchedCreateServer(...args) {
  const nextListener = typeof args[args.length - 1] === 'function' ? args.pop() : null
  const server = origCreateServer.apply(this, args)
  const origOn = server.on.bind(server)

  // Prevent Next.js's internal upgrade handler from closing /api/v1/* WebSocket sockets
  server.on = function patchedOn(event, listener) {
    if (event === 'upgrade') {
      return origOn('upgrade', (req, socket, head) => {
        if (req.url?.startsWith('/api/v1/')) {
          return
        }
        return listener(req, socket, head)
      })
    }
    return origOn(event, listener)
  }

  if (nextListener) {
    origOn('request', (req, res) => {
      if (
        req.url === '/health' ||
        req.url?.startsWith('/health?') ||
        req.url?.startsWith('/api/v1/')
      ) {
        const proxyHeaders = {
          ...req.headers,
          host: `${FASTAPI_HOST}:${FASTAPI_PORT}`,
        }
        const proxyReq = http.request(
          {
            hostname: FASTAPI_HOST,
            port: FASTAPI_PORT,
            path: req.url,
            method: req.method,
            headers: proxyHeaders,
          },
          (proxyRes) => {
            res.writeHead(proxyRes.statusCode || 200, proxyRes.headers)
            proxyRes.pipe(res)
          },
        )
        proxyReq.on('error', (err) => {
          console.error('FastAPI proxy error:', err.message)
          if (!res.headersSent) res.writeHead(502)
          res.end('Bad Gateway')
        })
        req.pipe(proxyReq)
        return
      }
      nextListener(req, res)
    })
  }

  origOn('upgrade', (req, socket, head) => {
    if (!req.url?.startsWith('/api/v1/')) {
      return
    }
    socket.on('error', (err) => {
      console.error('WebSocket client socket error:', err.message)
    })
    const upstream = net.connect(FASTAPI_PORT, FASTAPI_HOST, () => {
      const headerLines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`]
      for (let i = 0; i < req.rawHeaders.length; i += 2) {
        const k = req.rawHeaders[i]
        const v = req.rawHeaders[i + 1]
        if (k.toLowerCase() === 'host') {
          headerLines.push(`Host: ${FASTAPI_HOST}:${FASTAPI_PORT}`)
        } else {
          headerLines.push(`${k}: ${v}`)
        }
      }
      headerLines.push('', '')
      upstream.write(headerLines.join('\r\n'))
      if (head && head.length > 0) {
        upstream.write(head)
      }
      socket.pipe(upstream).pipe(socket)
    })

    upstream.on('error', (err) => {
      console.error('WebSocket upstream socket error:', err.message)
      socket.destroy()
    })
    socket.on('close', () => {
      upstream.destroy()
    })
    upstream.on('close', () => {
      socket.destroy()
    })
  })

  return server
}

require('./server.js')
