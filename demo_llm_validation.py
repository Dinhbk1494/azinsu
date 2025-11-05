#!/usr/bin/env python3
"""
Demo đơn giản cho tính năng LLM validation
"""

import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simple_disease_checker_improved import check_drug_list_by_multi_diseases_ilike

async def demo_llm_validation():
    """Demo tính năng LLM validation"""
    
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    print("🚀 DEMO: LLM VALIDATION FOR DRUG MATCHING")
    print("=" * 60)
    
    # Test case đơn giản
    diagnosis = "Viêm họng cấp tính"
    drugs = ["Paracetamol"]  # Chỉ test 1 thuốc để dễ quan sát
    
    print(f"📋 Test Case:")
    print(f"   Diagnosis: {diagnosis}")
    print(f"   Drug: {drugs[0]}")
    print()
    
    try:
        # Test without LLM validation
        print("📊 WITHOUT LLM VALIDATION:")
        result_no_llm = await check_drug_list_by_multi_diseases_ilike(
            diagnosis, drugs, database_url, use_llm_filter=False
        )
        
        print(f"   Found {result_no_llm['results'][0]['matched_count']} matches:")
        for i, match in enumerate(result_no_llm['results'][0]['matches'][:5], 1):
            print(f"   {i}. {match['name']}")
        
        # Test with LLM validation
        print(f"\n📊 WITH LLM VALIDATION:")
        result_with_llm = await check_drug_list_by_multi_diseases_ilike(
            diagnosis, drugs, database_url, use_llm_filter=True
        )
        
        print(f"   Found {result_with_llm['results'][0]['matched_count']} matches:")
        for i, match in enumerate(result_with_llm['results'][0]['matches'][:5], 1):
            print(f"   {i}. {match['name']}")
            if match.get('llm_validation'):
                llm_info = match['llm_validation']
                print(f"      ✅ LLM: {llm_info['confidence']} confidence")
                print(f"      📝 Reason: {llm_info['reason']}")
        
        # Summary
        original_count = result_no_llm['results'][0]['matched_count']
        filtered_count = result_with_llm['results'][0]['matched_count']
        print(f"\n📈 SUMMARY:")
        print(f"   Original matches: {original_count}")
        print(f"   After LLM filter: {filtered_count}")
        print(f"   Filtered out: {original_count - filtered_count}")
        
        if original_count - filtered_count > 0:
            print("   ✅ LLM successfully filtered out inappropriate matches!")
        else:
            print("   ℹ️  LLM kept all matches (they were all appropriate)")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def demo_multiple_drugs():
    """Demo với nhiều thuốc"""
    
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    print("\n" + "=" * 60)
    print("🚀 DEMO: MULTIPLE DRUGS WITH LLM VALIDATION")
    print("=" * 60)
    
    diagnosis = "Viêm tai giữa"
    drugs = ["Ileffexime", "Cefprozil"]
    
    print(f"📋 Test Case:")
    print(f"   Diagnosis: {diagnosis}")
    print(f"   Drugs: {', '.join(drugs)}")
    print()
    
    try:
        # Test with LLM validation
        result = await check_drug_list_by_multi_diseases_ilike(
            diagnosis, drugs, database_url, use_llm_filter=True
        )
        
        for i, drug_result in enumerate(result['results']):
            print(f"🔍 {drug_result['input_name']}:")
            print(f"   Matched: {drug_result['matched']}")
            print(f"   Count: {drug_result['matched_count']} matches")
            
            for j, match in enumerate(drug_result['matches'][:3], 1):
                print(f"   {j}. {match['name']}")
                if match.get('llm_validation'):
                    llm_info = match['llm_validation']
                    print(f"      ✅ LLM: {llm_info['confidence']} confidence")
                    if llm_info['reason']:
                        print(f"      📝 Reason: {llm_info['reason'][:100]}...")
            print()
        
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    """Main demo function"""
    await demo_llm_validation()
    await demo_multiple_drugs()
    
    print("=" * 60)
    print("✅ DEMO COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
