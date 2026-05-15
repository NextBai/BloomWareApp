def test_typewriter_avoids_interval_and_full_markdown_rerender_per_tick():
    source = open("static/frontend/js/ui.js", encoding="utf-8").read()
    start = source.index("function typewriterEffect")
    block = source[start:source.index("const agentProgressSteps")]

    assert "setInterval(" not in block
    assert "requestAnimationFrame(" in block
    assert "renderAgentMarkdown(text.slice(0, index))" not in block
    assert "typewriterTextNode" in source
    assert "typewriterFrameId" in source
    assert "setTypewriterContent" in source


def test_streaming_output_skips_redundant_full_repaint_when_text_unchanged():
    source = open("static/frontend/js/ui.js", encoding="utf-8").read()

    assert "let lastRenderedAgentText = '';" in source
    assert "if (lastRenderedAgentText === nextText)" in source
    assert "lastRenderedAgentText = nextText;" in source


def test_final_typewriter_waits_for_speech_completion_before_idle():
    ui_source = open("static/frontend/js/ui.js", encoding="utf-8").read()
    tts_source = open("static/frontend/js/tts.js", encoding="utf-8").read()

    assert "const awaitSpeechCompletion = options.awaitSpeechCompletion === true || !!enableTTS;" in ui_source
    assert "window.agentOutputAwaitingSpeechCompletion = awaitSpeechCompletion;" in ui_source
    assert "if (window.agentOutputAwaitingSpeechCompletion) {" in ui_source
    assert "function maybeFinalizeSpeechPlayback()" in tts_source
    assert "window.agentOutputAwaitingSpeechCompletion = false;" in tts_source
    assert "maybeFinalizeSpeechPlayback();" in tts_source


def test_progress_updates_do_not_override_active_answer_stream():
    ui_source = open("static/frontend/js/ui.js", encoding="utf-8").read()
    ws_source = open("static/frontend/js/websocket.js", encoding="utf-8").read()

    assert "window.agentOutputHasAnswerStream = false;" in ui_source
    assert "if (options.progress === true && window.agentOutputHasAnswerStream) {" in ui_source
    assert "window.agentOutputHasAnswerStream = true;" in ui_source
    assert "if (typeof currentState !== 'undefined' && currentState === 'speaking') {" in ws_source
    assert "setState('speaking');" in ws_source


def test_stt_idle_does_not_reset_agent_while_speaking():
    ws_source = open("static/frontend/js/websocket.js", encoding="utf-8").read()

    assert "else if (data.status === 'idle' || data.status === 'error') {" in ws_source
    assert "if (typeof currentState !== 'undefined' && currentState === 'speaking') {" in ws_source
    assert "resetAgent();" in ws_source


def test_final_output_can_wait_for_streaming_speech_completion_without_full_tts():
    ui_source = open("static/frontend/js/ui.js", encoding="utf-8").read()
    tts_source = open("static/frontend/js/tts.js", encoding="utf-8").read()
    ws_source = open("static/frontend/js/websocket.js", encoding="utf-8").read()

    assert "const awaitSpeechCompletion = options.awaitSpeechCompletion === true || !!enableTTS;" in ui_source
    assert "function hasPendingStreamingSpeech()" in tts_source
    assert "|| !!ttsStreamSocket || _ttsActiveSources.length > 0" in tts_source
    assert "hasPendingStreamingSpeech() || useFullTtsFallback" in ws_source
    assert "finishAgentOutput(data.message, useFullTtsFallback, {" in ws_source


def test_tts_debug_logging_and_stop_reason_contracts_exist():
    tts_source = open("static/frontend/js/tts.js", encoding="utf-8").read()
    agent_source = open("static/frontend/js/agent.js", encoding="utf-8").read()

    assert "function logTtsDebug(event, extra = {})" in tts_source
    assert "if (!window.DEBUG_MODE) {" in tts_source
    assert "logTtsDebug('socket_close'" in tts_source
    assert "function stopSpeaking(clearPending = true, reason = 'unspecified')" in tts_source
    assert "stopSpeaking(true, 'state_idle');" in agent_source
    assert "stopSpeaking(true, 'reset_agent');" in agent_source


def test_complete_typewriter_refuses_idle_while_streaming_speech_still_pending():
    ui_source = open("static/frontend/js/ui.js", encoding="utf-8").read()

    assert "if (typeof hasPendingStreamingSpeech === 'function' && hasPendingStreamingSpeech()) {" in ui_source
    assert "window.agentOutputAwaitingSpeechCompletion = true;" in ui_source


def test_tool_cards_container_is_an_interactive_fixed_overlay():
    source = open("static/frontend/index.html", encoding="utf-8").read()

    assert "#tool-cards-container {" in source
    assert "position: fixed;" in source
    assert "pointer-events: none;" in source
    assert "#tool-cards-container .voice-tool-card {" in source
    assert "pointer-events: auto;" in source


def test_tool_card_visual_dividers_and_scrollbar_are_refined():
    source = open("static/frontend/index.html", encoding="utf-8").read()

    assert "border: 1px solid rgba(15, 23, 42, 0.06);" in source
    assert "border-bottom: 1px solid rgba(15, 23, 42, 0.05);" in source
    assert ".tool-drawer-content::-webkit-scrollbar {" in source
    assert "width: 3px;" in source
    assert "background: rgba(15, 23, 42, 0.12);" in source


def test_speaking_petals_reuse_idle_rotation_and_layer_interleave():
    source = open("static/frontend/index.html", encoding="utf-8").read()

    assert ".voice-mic-container.speaking .bloom-petal-group.upper .bloom-petal:nth-child(1)" in source
    assert "animation: petalBloom 1.6s ease-in-out infinite 0s;" in source
    assert ".voice-mic-container.speaking .bloom-petal-group.lower .bloom-petal:nth-child(1)" in source
    assert "animation: petalBloomInner 1.6s ease-in-out infinite 0.1s;" in source
    assert "--speaking-angle" not in source
    assert "speakingPetalFloat" not in source
    assert "speakingPetalFloatInner" not in source


def test_websocket_updates_conversation_language_from_bot_messages():
    ws_source = open("static/frontend/js/websocket.js", encoding="utf-8").read()

    assert "if (data.language) {" in ws_source
    assert "window.currentConversationLanguage = data.language;" in ws_source
    assert "window.currentSpeechLanguage = data.language;" in ws_source


def test_new_thinking_cycle_clears_stale_tts_language_before_next_stream():
    ws_source = open("static/frontend/js/websocket.js", encoding="utf-8").read()

    assert "window.currentConversationLanguage = null;" in ws_source
    assert "window.currentSpeechLanguage = null;" in ws_source


def test_bot_delta_carries_language_for_streaming_tts_switch():
    source = open("app.py", encoding="utf-8").read()

    assert "\"language\": _preferred_language_from_text(stream_accumulator[\"text\"]) or resolved_language" in source


def test_frontend_preloads_conversation_language_on_initial_input():
    ws_source = open("static/frontend/js/websocket.js", encoding="utf-8").read()

    assert "function inferConversationLanguage(text, fallback = null)" in ws_source
    assert "const inferredLanguage = window.inferConversationLanguage(text, navigator.language || 'zh-TW');" in ws_source
    assert "window.currentConversationLanguage = inferredLanguage;" in ws_source
    assert "window.currentSpeechLanguage = inferredLanguage;" in ws_source
