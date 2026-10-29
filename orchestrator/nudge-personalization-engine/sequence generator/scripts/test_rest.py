import asyncio
import sys
sys.path.insert(0, '.')
from tools.mcp_client import MessageGeneratorMCPClient

async def test():
    client = MessageGeneratorMCPClient()
    print(f'Connection mode: {client.connection_mode}')
    print(f'SSE URL: {client.sse_url}')
    print(f'Server CWD: {client.server_cwd}')
    
    result = await client.generate_outreach(
        target_prospect='Test User',
        target_company='Test Company',
        company_name='My Company',
        offer_name='Test Offer'
    )
    
    print(f'Success: {result.get("success")}')
    if result.get('success'):
        print(f'Message: {result.get("message")[:100]}...')
    else:
        print(f'Error: {result.get("error")[:200]}')

if __name__ == "__main__":
    asyncio.run(test())
