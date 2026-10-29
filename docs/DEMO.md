# Interactive demo

The demo runs the actual frontend on a separate loopback-only Vite server with
synthetic case and session fixtures. It does not start the backend, n8n,
authentication service, PDF worker or an AI provider. It does not save documents.

```sh
npm --prefix frontend ci
npm --prefix frontend run demo
```

Open http://127.0.0.1:5198, select **Project delivery agreement.pdf** and explore
the case tabs. The evidence preview is synthetic. The assistant offers two recorded responses generated once by Anthropic from the synthetic excerpts. Select Deadlines or Risks & approvals; other questions are not supported. The demo does not call AI or verify the answers live. Uploads,
account changes and unknown API requests are blocked. Restart the server to reset
the demo. The demo must not be exposed to a network or used for real documents.

This demonstration uses mocked APIs. It does not validate authentication,
security controls, actual PDF processing or the accuracy of AI answers.

Watch the [narrated walkthrough](demo/README.md), with English narration and Greek subtitles. It uses screenshots of this synthetic demo.
