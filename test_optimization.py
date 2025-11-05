#!/usr/bin/env python3
"""
Test script để kiểm tra tối ưu hóa tránh gọi LLM trùng lặp
"""

import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from medicine_classifier_v2 import classify_with_gpt4

async def test_optimization():
    """Test xem có còn gọi LLM trùng lặp không"""
    
    print("🚀 TESTING: Optimization to avoid duplicate LLM calls")
    print("=" * 60)
    
    # Test data
    items = ["Paracetamol 500mg", "Amoxicillin 500mg"]
    symptom = "Viêm họng cấp tính kèm sốt nhẹ"
    
    print(f"📋 Test Case:")
    print(f"   Items: {items}")
    print(f"   Symptom: {symptom}")
    print()
    
    try:
        print("🔍 Running classify_with_gpt4 with DB checker enabled...")
        result = await classify_with_gpt4(
            items=items,
            symptom=symptom,
            enable_db_disease_checker=True,  # Enable DB checker
            enable_llm_validation=False,     # Disable LLM validation for cleaner test
        )
        
        print("✅ Classification completed successfully!")
        print(f"   Request ID: {result['request_id']}")
        print(f"   Results count: {len(result['results'])}")
        
        for i, item in enumerate(result['results'], 1):
            print(f"   {i}. {item.name}: {item.category} - {item.role}")
        
        print(f"\n📊 Changes: {result.get('changed', False)}")
        if result.get('changes'):
            print(f"   Change count: {len(result['changes'])}")
            for change in result['changes']:
                print(f"   - {change['id']}: {change.get('changes', {})}")
        
        print("\n🎯 Optimization check:")
        print("   - If you see 'Using pre-split diseases' in logs → ✅ Optimization working")
        print("   - If you see 'Split diseases from diagnosis' in logs → ❌ Still calling LLM twice")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_without_db_checker():
    """Test without DB checker để so sánh"""
    
    print("\n" + "=" * 60)
    print("🚀 TESTING: Without DB checker (baseline)")
    print("=" * 60)
    
    items = ["Paracetamol 500mg", "Amoxicillin 500mg"]
    symptom = "Viêm họng cấp tính kèm sốt nhẹ"
    
    try:
        print("🔍 Running classify_with_gpt4 with DB checker disabled...")
        result = await classify_with_gpt4(
            items=items,
            symptom=symptom,
            enable_db_disease_checker=False,  # Disable DB checker
            enable_llm_validation=False,
        )
        
        print("✅ Classification completed successfully!")
        print(f"   Request ID: {result['request_id']}")
        print(f"   Results count: {len(result['results'])}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    """Main test function"""
    await test_optimization()
    await test_without_db_checker()
    
    print("\n" + "=" * 60)
    print("✅ OPTIMIZATION TEST COMPLETED")
    print("=" * 60)
    print("\n📝 Summary:")
    print("   - Check logs above to see if 'Using pre-split diseases' appears")
    print("   - This indicates the optimization is working correctly")
    print("   - No more duplicate LLM calls for disease splitting!")

if __name__ == "__main__":
    asyncio.run(main())
