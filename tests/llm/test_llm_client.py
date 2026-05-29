import pytest
from unittest.mock import MagicMock
from tostr.llm.base import LLMClient, LLMStrategy, LLMResponse
from tostr.core.models import BaseClass, BaseMethod, BaseFile
from tostr.core.registry import Registry

class MockStrategy(LLMStrategy):
    async def describe_class(self, input_data_string: str, system_instruction: str) -> LLMResponse:
        return LLMResponse(
            description="Mock class description",
            description_map={0: "Mock method description"},
            status="success"
        )

@pytest.mark.asyncio
async def test_llm_client_data_flow():
    """
    Test that LLMClient correctly calls the strategy and maps method descriptions
    back to the method objects using the description_map.
    """
    strategy = MockStrategy(api_key="test", model_name="test")
    client = LLMClient(strategy)
    
    # Create a mock method
    mock_method = MagicMock(spec=BaseMethod, uid="mock.method", name="method")
    mock_method.parent = MagicMock(spec=BaseFile, imports=[]) # Mock the parent file
    mock_method.signature = "void test()"
    mock_method.description = ""
    
    # Create a mock class
    mock_class = MagicMock(spec=BaseClass)
    mock_class.uid = "class_uid"
    mock_class.methods = [mock_method]
    mock_class.skeletonize.return_value = "class code"
    
    response = await client.describe_class(mock_class, [])
    
    # Verify class description in response
    assert response.description == "Mock class description"
    # Verify that the client mapped the method description back to the mock_method object
    assert mock_method.description == "Mock method description"

@pytest.mark.asyncio
async def test_models_resolve_description_data_flow():
    """
    Test the full data flow from BaseClass.resolve_description_async through LLMClient.
    """
    registry = MagicMock(spec=Registry)
    parent_file = MagicMock(spec=BaseFile, imports=[], package="com.example")
    
    # Create a real BaseClass instance
    cls = BaseClass(name="TestClass", uid="TestClass")
    cls.registry = registry
    cls.parent = parent_file
    
    # Create a real BaseMethod instance
    method = BaseMethod(name="testMethod", uid="TestClass#testMethod")
    cls.add_child(method)
    
    # Mock skeletonize because it normally requires a tree-sitter node reference
    cls.skeletonize = MagicMock(return_value="class skeleton")
    
    strategy = MockStrategy(api_key="test", model_name="test")
    client = LLMClient(strategy)
    
    # This should trigger the LLM call and update descriptions
    await cls.resolve_description_async(client)
    
    # Verify descriptions were updated
    assert cls.description == "Mock class description"
    assert method.description == "Mock method description"

@pytest.mark.asyncio
async def test_llm_client_retry_logic():
    """
    Test that LLMClient correctly handles retries on server busy errors.
    """
    class RetryStrategy(LLMStrategy):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.attempts = 0
            
        async def describe_class(self, input_data_string: str, system_instruction: str) -> LLMResponse:
            self.attempts += 1
            if self.attempts == 1:
                raise Exception("503 Server Busy")
            return LLMResponse(
                description="Success after retry",
                status="success"
            )

    strategy = RetryStrategy(api_key="test", model_name="test")
    client = LLMClient(strategy)
    
    mock_class = MagicMock(
        spec=BaseClass,
        uid="mock.class",
        methods=[],
        skeletonize=MagicMock(return_value="code")
    )
    
    # We need to mock asyncio.sleep to avoid waiting during tests
    with MagicMock() as mock_sleep:
        import asyncio
        original_sleep = asyncio.sleep
        asyncio.sleep = MagicMock(return_value=original_sleep(0))
        
        response = await client.describe_class(mock_class, [])
        
        asyncio.sleep = original_sleep
    
    assert response.description == "Success after retry"
    assert strategy.attempts == 2
