# Files into Model Context

The global shell command stages a local file as multimodal model input:

```sh
macagentic-read-file PATH
```

The command accepts PDF and image files up to 20 MiB. It does not check
whether the current model supports the specific format.

Each successful read copies an immutable, sequentially numbered snapshot into
`$AGENT_ROOT/context/`. Relative, absolute, and `~` paths follow normal shell
semantics.

The agent maps staged PDFs to Responses API `input_file` content and staged
images to `input_image` content. Conversation state stores the staged path and
metadata, not inline base64.

Missing, unsupported, and oversized files produce ordinary shell-tool errors.
If the model provider rejects a staged file, the attachment is replaced with a
text error and the LLM decides how to proceed.
