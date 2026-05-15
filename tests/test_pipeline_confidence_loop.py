import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from core.pipeline import ChatPipeline, PipelineResult

@pytest.mark.asyncio
async def test_confidence_driven_loop_no_tool_calls():
    """Test when no tools are called, it immediately answers."""
    intent_detector = AsyncMock()
    # Returns no feature
    intent_detector.return_value = (False, {"emotion": "neutral"})
    
    feature_processor = AsyncMock()
    ai_generator = AsyncMock()
    ai_generator.return_value = PipelineResult(text="Hello", is_fallback=False, meta={"emotion": "neutral"})
    
    pipeline = ChatPipeline(
        intent_detector=intent_detector,
        feature_processor=feature_processor,
        ai_generator=ai_generator
    )
    
    res = await pipeline.process("Hello")
    assert res.text == "Hello"
    assert intent_detector.call_count == 1
    assert feature_processor.call_count == 0
    assert ai_generator.call_count == 1

@pytest.mark.asyncio
async def test_confidence_driven_loop_single_tool_call():
    """Test when one tool is called, it iterates once and passes context."""
    intent_detector = AsyncMock()
    # 1st call: Call tool
    # 2nd call: No tool needed (satisfied)
    intent_detector.side_effect = [
        (True, {"type": "mcp_tool", "confidence": 0.95, "emotion": "neutral"}),
        (False, {"emotion": "neutral"})
    ]
    
    feature_processor = AsyncMock()
    feature_processor.return_value = PipelineResult(text="Tool result payload", is_fallback=False, meta={})
    
    ai_generator = AsyncMock()
    ai_generator.return_value = "Based on the tool, the answer is Yes."
    
    pipeline = ChatPipeline(
        intent_detector=intent_detector,
        feature_processor=feature_processor,
        ai_generator=ai_generator
    )
    
    res = await pipeline.process("What is the weather?")
    
    assert res.text == "Based on the tool, the answer is Yes."
    assert intent_detector.call_count == 2
    assert feature_processor.call_count == 1
    assert ai_generator.call_count == 1
    
    # Verify tool context is passed to ai_generator
    call_kwargs = ai_generator.call_args.kwargs
    assert "Tool result payload" in call_kwargs.get("tool_context", "")

@pytest.mark.asyncio
async def test_confidence_driven_loop_multi_tool_call():
    """Test when information is incomplete, it calls multiple tools before answering."""
    intent_detector = AsyncMock()
    # 1st call: Call tool 1
    # 2nd call: Call tool 2
    # 3rd call: Satisfied
    intent_detector.side_effect = [
        (True, {"type": "mcp_tool", "confidence": 0.95, "emotion": "neutral"}),
        (True, {"type": "mcp_tool", "confidence": 0.95, "emotion": "neutral"}),
        (False, {"emotion": "neutral"})
    ]
    
    feature_processor = AsyncMock()
    feature_processor.side_effect = [
        PipelineResult(text="Tool 1 result", is_fallback=False, meta={}),
        PipelineResult(text="Tool 2 result", is_fallback=False, meta={})
    ]
    
    ai_generator = AsyncMock()
    ai_generator.return_value = "Combined answer."
    
    pipeline = ChatPipeline(
        intent_detector=intent_detector,
        feature_processor=feature_processor,
        ai_generator=ai_generator
    )
    
    res = await pipeline.process("Complex query")
    
    assert res.text == "Combined answer."
    assert intent_detector.call_count == 3
    assert feature_processor.call_count == 2
    assert ai_generator.call_count == 1
    
    call_kwargs = ai_generator.call_args.kwargs
    context = call_kwargs.get("tool_context", "")
    assert "Tool 1 result" in context
    assert "Tool 2 result" in context
