#!/usr/bin/env python3
"""
Test script để demo tính năng LLM validation cho drug matching
"""

import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simple_disease_checker_improved import check_drug_list_by_multi_diseases_ilike

async def test_llm_validation():
    """Test LLM validation với các trường hợp khác nhau"""
    
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    test_cases = [
        {
            "name": "Test Case 1: Thuốc có nhiều dạng bào chế",
            "diagnosis": "Viêm họng cấp tính",
            "drugs": ["Paracetamol", "Amoxicillin"],
            "expected_issue": "Có thể tìm thấy Paracetamol viên, siro, tiêm - LLM sẽ lọc ra dạng phù hợp"
        },
        {
            "name": "Test Case 2: Thuốc có nhiều hàm lượng",
            "diagnosis": "Viêm tai giữa",
            "drugs": ["Ileffexime", "Cefprozil"],
            "expected_issue": "Có thể tìm thấy các hàm lượng khác nhau - LLM sẽ giữ lại hàm lượng phù hợp"
        },
        {
            "name": "Test Case 3: Thuốc có tên giống nhưng khác hoạt chất",
            "diagnosis": "Viêm dạ dày",
            "drugs": ["Omeprazole", "Metronidazole"],
            "expected_issue": "Có thể tìm thấy thuốc tên giống nhưng khác hoạt chất - LLM sẽ loại bỏ"
        }
    ]
    
    print("=" * 80)
    print("TESTING LLM VALIDATION FOR DRUG MATCHING")
    print("=" * 80)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🔍 {test_case['name']}")
        print(f"Diagnosis: {test_case['diagnosis']}")
        print(f"Drugs: {test_case['drugs']}")
        print(f"Expected issue: {test_case['expected_issue']}")
        print("-" * 60)
        
        try:
            # Test without LLM validation
            print("📊 WITHOUT LLM VALIDATION:")
            result_no_llm = await check_drug_list_by_multi_diseases_ilike(
                test_case['diagnosis'], 
                test_case['drugs'], 
                database_url, 
                use_llm_filter=False
            )
            
            for result in result_no_llm['results']:
                print(f"  {result['input_name']}: {result['matched_count']} matches")
                for match in result['matches'][:3]:
                    print(f"    • {match['name']}")
            
            # Test with LLM validation
            print("\n📊 WITH LLM VALIDATION:")
            result_with_llm = await check_drug_list_by_multi_diseases_ilike(
                test_case['diagnosis'], 
                test_case['drugs'], 
                database_url, 
                use_llm_filter=True
            )
            
            for result in result_with_llm['results']:
                print(f"  {result['input_name']}: {result['matched_count']} matches (after LLM filter)")
                for match in result['matches'][:3]:
                    print(f"    • {match['name']}")
                    if match.get('llm_validation'):
                        llm_info = match['llm_validation']
                        print(f"      - LLM: {llm_info['confidence']} confidence")
                        print(f"      - Reason: {llm_info['reason']}")
            
            # Compare results
            print("\n📈 COMPARISON:")
            for j, drug in enumerate(test_case['drugs']):
                no_llm_count = result_no_llm['results'][j]['matched_count']
                with_llm_count = result_with_llm['results'][j]['matched_count']
                filtered = no_llm_count - with_llm_count
                
                print(f"  {drug}: {no_llm_count} → {with_llm_count} ({filtered} filtered out)")
            
        except Exception as e:
            print(f"❌ Error in test case {i}: {e}")
        
        print("=" * 60)

async def test_specific_drug_scenarios():
    """Test các trường hợp cụ thể về thuốc"""
    
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    print("\n" + "=" * 80)
    print("TESTING SPECIFIC DRUG SCENARIOS")
    print("=" * 80)
    
    # Test case đặc biệt: thuốc có thể có nhiều dạng
    diagnosis = "Viêm họng cấp tính"
    drugs = ["Paracetamol"]  # Chỉ test 1 thuốc để dễ quan sát
    
    print(f"🔍 Testing: {drugs[0]} for '{diagnosis}'")
    print("Expected: LLM should filter out inappropriate formulations")
    
    try:
        # Without LLM
        result_no_llm = await check_drug_list_by_multi_diseases_ilike(
            diagnosis, drugs, database_url, use_llm_filter=False
        )
        
        print(f"\n📊 WITHOUT LLM VALIDATION:")
        print(f"Found {result_no_llm['results'][0]['matched_count']} matches:")
        for match in result_no_llm['results'][0]['matches'][:5]:
            print(f"  • {match['name']}")
        
        # With LLM
        result_with_llm = await check_drug_list_by_multi_diseases_ilike(
            diagnosis, drugs, database_url, use_llm_filter=True
        )
        
        print(f"\n📊 WITH LLM VALIDATION:")
        print(f"Found {result_with_llm['results'][0]['matched_count']} matches:")
        for match in result_with_llm['results'][0]['matches'][:5]:
            print(f"  • {match['name']}")
            if match.get('llm_validation'):
                llm_info = match['llm_validation']
                print(f"    - Confidence: {llm_info['confidence']}")
                print(f"    - Reason: {llm_info['reason']}")
        
        # Summary
        original_count = result_no_llm['results'][0]['matched_count']
        filtered_count = result_with_llm['results'][0]['matched_count']
        print(f"\n📈 SUMMARY:")
        print(f"  Original matches: {original_count}")
        print(f"  After LLM filter: {filtered_count}")
        print(f"  Filtered out: {original_count - filtered_count}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    """Main test function"""
    print("🚀 Starting LLM Validation Tests")
    
    await test_llm_validation()
    await test_specific_drug_scenarios()
    
    print("\n" + "=" * 80)
    print("✅ ALL LLM VALIDATION TESTS COMPLETED")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
