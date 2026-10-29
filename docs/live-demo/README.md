# Local application walkthrough with live AI questions

A 2 minute 18 second narrated walkthrough of the actual local frontend and
backend, using a synthetic tax-policy PDF and a dedicated demo account. The edit
assembles 101 sequential screenshots captured during the real interaction;
it is a low-frame-rate screen capture, not continuous full-frame-rate video.
The English narration was generated locally using Microsoft Zira Desktop.

- [Video](nomikos-live-demo.mp4)
- [Greek subtitles](captions-el.srt) · [English subtitles](captions-en.srt)
- [Narration and scene descriptions](storyboard.json)

Two questions were submitted through the real document assistant. The normal
application pipeline may issue additional provider requests for retrieval,
evaluation and auditing. The video shows the returned answers rather than
replaying the isolated synthetic-demo fixture.

## Results and limitations

The saved case had zero extracted facts, obligations, actions and decisions,
although the synthetic source includes such content. The first assistant answer
misreported a 15 July date as 16 July, reflecting an OCR error; its automated
verification was unavailable. The second answer did not retrieve relevant
risk details present elsewhere in the document. These are actual limitations,
not validated conclusions. The document is a test fixture and is not tax advice.

No real customer document or paid voice service was used. The provider usage
was authorized by the owner; actual billing must be checked in the provider
account. This local recording is not evidence of production security, accurate
AI performance, or a successful hosted release. [Release gate](../SECURITY_RELEASE_GATE.md).
