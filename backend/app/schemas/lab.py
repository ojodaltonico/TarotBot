from datetime import datetime
from pydantic import BaseModel, Field
class LabChatRequest(BaseModel): user_key:str=Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9_-]+$");message:str=Field(min_length=1,max_length=2000);message_id:str|None=Field(default=None,max_length=255)
class LabReadingRequest(BaseModel): spread_type:str|None=Field(default=None,max_length=64);question:str|None=Field(default=None,max_length=2000)
class UsageResponse(BaseModel): provider:str;model:str;input_tokens:int;output_tokens:int;estimated_cost_usd:float|None
class MetricsResponse(BaseModel): calls:int;total_ai_calls:int;successful_ai_calls:int;failed_ai_calls:int;total_input_tokens:int;total_output_tokens:int;total_cached_tokens:int;estimated_cost_usd:float|None;calls_with_known_cost:int;calls_with_unknown_cost:int
class MessageResponse(BaseModel): direction:str;content:str
class CardResponse(BaseModel): position:str;card_id:str;orientation:str
class ReadingSummaryResponse(BaseModel): reading_id:int;spread:str;created_at:str;cards:list[CardResponse]
class InterpretationErrorResponse(BaseModel): category:str;provider:str;model:str;http_status:int|None=None;google_status:str|None=None;request_id:str|None=None
class LabReadingResponse(BaseModel): reading_id:int;spread:str;cards:list[dict];interpretation:str|None;summary:str|None;state:str;interpretation_error:InterpretationErrorResponse|None=None
class LabChatResponse(BaseModel): reply:str;state:str;intent:str;reading_recommended:bool;suggested_spread:str|None;usage:UsageResponse|None;reading:LabReadingResponse|None=None
class LabUserStateResponse(BaseModel): user_key:str;user_id:int;conversation_id:int;state:str;last_intent:str|None;reading_recommended:bool;suggested_spread:str|None;memory:str|None;memory_version:int|None;message_count:int;messages:list[MessageResponse];last_reading_id:int|None;last_reading:ReadingSummaryResponse|None;last_interpretation:str|None;metrics:MetricsResponse
class LabMemoryRefreshResponse(BaseModel): updated:bool;version:int|None;summary:str|None;reason:str|None
class LabResetResponse(BaseModel): reset:bool;user_key:str
