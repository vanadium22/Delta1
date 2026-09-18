import os
import sys
import oracledb
import pandas as pd
from utils.tool_config import *
import utils.config
import math
import warnings

if __package__:
    from .wind_connection import connect as _wind_connect
else:
    from wind_connection import connect as _wind_connect


def ignore_warning():
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        message="DataFrameGroupBy.apply operated on the grouping columns")
    


# Native Oracle client selection is handled by wind_connection.connect().




datalist = ['RD_EXPENSE','NET_PROFIT_AFTER_DED_NR_LP','S_DFA_EQUITY','S_DQ_AMOUNT','TOT_ASSETS','S_VAL_PB_NEW','TOT_SHRHLDR_EQY_EXCL_MIN_INT','S_VAL_MV','NET_PROFIT','EST_BPS','EST_BASESHARE']
col_list =  ['S_INFO_WINDCODE','TRADE_DT','ANN_DT','REPORT_PERIOD']

class Download_wind:

    def __init__(self):
        self.db = _wind_connect()

    def dl_general(self, sql):

        cursor = self.db.cursor()
        cursor.execute(sql)
        result = cursor.fetchall()
        columns = [i[0] for i in cursor.description]
        df = pd.DataFrame(result, columns=columns)
        return df

class DownloadValue:
    
    def __init__(self,start_date,end_date):
        
        self.start_date = start_date
        self.end_date = end_date
        self.data_list = datalist
    
    def _int_to_date(self,d: int):
        """20250101 -> datetime.date(2025, 1, 1)"""
        year = d // 10000
        month = (d // 100) % 100
        day = d % 100
        return datetime(year, month, day).date()

    def _date_to_int(self,dt):
        """datetime.date -> 20250101"""
        return dt.year * 10000 + dt.month * 100 + dt.day

    
    @staticmethod
    def drop_duplicated_with_tol(
        df: pd.DataFrame,
        tol: float = 1e-6,
    ) -> pd.DataFrame:
        """
        在大数据量场景下，做“带数值容差”的去重：
        - 对于数值列: |x - y| < tol 视为相同（通过 round 实现）
        - 对于非数值列: 必须完全相等
        - 多行完全相同时，只保留第一行

        参数
        ----
        df   : DataFrame，index 为数字，列较多
        tol  : 数值容差，默认 1e-6

        返回
        ----
        去重后的 DataFrame，保留原 index，不修改原 df
        """

        if df.empty:
            return df

        # 1. 建一个“轻量 copy”：不拷贝底层数据，只是新的 DataFrame 壳
        df_norm = df.copy(deep=False)

        # 2. 找出数值列（包括 int / float 等）
        num_cols = df_norm.select_dtypes(include=[np.number]).columns

        if len(num_cols) > 0:
            # 3. 决定保留的小数位数：tol=1e-6 → decimals=6
            decimals = max(0, int(round(-math.log10(tol))))

            # 仅对数值列做 round，生成新的数组（非数值列不拷贝）
            # 这一步是主要的额外内存消耗：只会多占一份“数值列块”的内存
            df_norm[num_cols] = df_norm[num_cols].round(decimals)

        # 4. 用归一化后的 df_norm 做重复判断，保留第一条
        mask = ~df_norm.duplicated(keep="first")

        # 5. 返回原始 df 中对应的行（不改原始数据）
        return df.loc[mask]
    
    def split_by_delta_days(self,start_int: int, end_int: int, delta_days: int):
        """
        将 [start_int, end_int] （闭区间，形如 20250101）按 delta_days 天一段切分。
        返回若干个 (sub_start, sub_end)，它们也是闭区间：
        TRADE_DT >= sub_start AND TRADE_DT <= sub_end
        并且这些子区间的并集 = 原来的 [start_int, end_int]，无重叠无缺口。
        """
        if delta_days <= 0:
            raise ValueError("delta_days 必须为正整数")

        start_date = self._int_to_date(start_int)
        end_date = self._int_to_date(end_int)

        ranges = []
        cur_start = start_date

        while cur_start <= end_date:
            # 当前段的结束日期 = cur_start + (delta_days - 1) 天
            cur_end = cur_start + timedelta(days=delta_days - 1)
            if cur_end > end_date:
                cur_end = end_date

            ranges.append((self._date_to_int(cur_start), self._date_to_int(cur_end)))

            # 下一段的开始日期 = 当前段结束 + 1 天
            cur_start = cur_end + timedelta(days=1)

        return ranges
    
    def RD_EXPENSE_DLDnSAVE(self):
        name = 'RD_EXPENSE'
 
        
        sql = f"""
        SELECT S_INFO_WINDCODE, ANN_DT, REPORT_PERIOD, {name}
        FROM WIND.ASHAREINCOME
        WHERE ANN_DT >= {self.start_date}
        AND ANN_DT <= {self.end_date}
        AND STATEMENT_TYPE = '408001000'
        """
        sql = sql.upper()
        
        
        dl_wind = Download_wind()
        all_bar = dl_wind.dl_general(sql)
        
        all_bar = self.drop_duplicated_with_tol(all_bar)
        DataOs.update_and_save_pkl_only_concat(all_bar,os.path.join(config.data_raw_folder_path,name +'.pkl'))
        # print(all_bar) 
    
    def TOT_ASSETS_DLDnSAVE(self):
        name = 'TOT_ASSETS'
 
        
        sql = f"""
        SELECT S_INFO_WINDCODE, ANN_DT, REPORT_PERIOD, {name}
        FROM WIND.AShareBalanceSheet
        WHERE ANN_DT >= {self.start_date}
        AND ANN_DT <= {self.end_date}
        """
        sql = sql.upper()
        
        
        dl_wind = Download_wind()
        all_bar = dl_wind.dl_general(sql)
        all_bar = self.drop_duplicated_with_tol(all_bar)
        DataOs.update_and_save_pkl_only_concat(all_bar,os.path.join(config.data_raw_folder_path,name +'.pkl'))
        # print(all_bar) 
    
    
    def TOT_SHRHLDR_EQY_EXCL_MIN_INT_DLDnSAVE(self):
        name = 'TOT_SHRHLDR_EQY_EXCL_MIN_INT'
 
        
        sql = f"""
        SELECT S_INFO_WINDCODE, ANN_DT, REPORT_PERIOD, {name}
        FROM WIND.AShareBalanceSheet
        WHERE ANN_DT >= {self.start_date}
        AND ANN_DT <= {self.end_date}
        """
        sql = sql.upper()
        
        
        dl_wind = Download_wind()
        all_bar = dl_wind.dl_general(sql)
        all_bar = self.drop_duplicated_with_tol(all_bar)
        DataOs.update_and_save_pkl_only_concat(all_bar,os.path.join(config.data_raw_folder_path,name +'.pkl'))
        # print(all_bar) 
    
    
    def NET_PROFIT_AFTER_DED_NR_LP_DLDnSAVE(self):
        name = 'NET_PROFIT_AFTER_DED_NR_LP'
 
        
        sql = f"""
        SELECT S_INFO_WINDCODE, ANN_DT, REPORT_PERIOD, {name}
        FROM WIND.ASHAREINCOME
        WHERE ANN_DT >= {self.start_date}
        AND ANN_DT <= {self.end_date}
        AND STATEMENT_TYPE = '408001000'
        """
        sql = sql.upper()
        
        
        dl_wind = Download_wind()
        all_bar = dl_wind.dl_general(sql)
        all_bar = self.drop_duplicated_with_tol(all_bar)
        DataOs.update_and_save_pkl_only_concat(all_bar,os.path.join(config.data_raw_folder_path,name +'.pkl'))
        # print(all_bar) 
        

    def S_DFA_EQUITY_DLDnSAVE(self, delta_days: int = 30):
        """
        分段下载 S_DFA_EQUITY，按 TRADE_DT 在 [self.start_date, self.end_date] 范围内，
        每段长度由 delta_days 控制（单位：天），分段下载并增量写入同一个 pkl。
        """
        name = 'S_DFA_EQUITY'
        save_path = os.path.join(config.data_raw_folder_path, name + '.pkl')

        # 一次建连接，循环复用
        dl_wind = Download_wind()

        # 依据 delta_days 切分 [start, end] 闭区间
        date_ranges = self.split_by_delta_days(self.start_date, self.end_date, delta_days)

        print(f"准备分 {len(date_ranges)} 段下载 {name}，delta_days={delta_days}")
        print(f"整体区间: [{self.start_date}, {self.end_date}]")
        # print(date_ranges)  # 如果想看具体切分结果，可以打开这一行

        for i, (sub_start, sub_end) in enumerate(date_ranges, start=1):
            sql = f"""
                SELECT S_INFO_WINDCODE,
                    TRADE_DT,
                    {name}
                FROM WIND.PITFinancialFactor
                WHERE TRADE_DT >= {sub_start}
                AND TRADE_DT <= {sub_end}
            """

            print(f"[{i}/{len(date_ranges)}] 下载区间: [{sub_start}, {sub_end}] ...")
            sub_df = dl_wind.dl_general(sql)
            sub_df = self.drop_duplicated_with_tol(sub_df)

            if sub_df.empty:
                print(f"[{i}/{len(date_ranges)}] 该区间无数据，跳过。")
                continue

            # 按 ANN_DT 排序并写入（update_and_save_pkl_only_concat 是你之前的工具函数）
            ok = DataOs.update_and_save_pkl_only_concat(
                sub_df,
                save_path,
                "TRADE_DT"   # 现在按公告日排序
            )
            if not ok:
                print(f"[{i}/{len(date_ranges)}] 保存失败！")
            else:
                print(f"[{i}/{len(date_ranges)}] 保存成功，本段行数: {len(sub_df)}")

        # 可选：最后读出看一眼
        try:
            final_df = pd.read_pickle(save_path)
            # print("最终合并后的 DataFrame 预览：")
            # print(final_df.head())
            print(f"总行数: {len(final_df)}")
        except Exception as e:
            print(f"最终读取 {save_path} 失败: {e}")
    
    def S_DQ_AMOUNT_DLDnSAVE(self, delta_days: int = 30):
        """
        分段下载 S_DQ_AMOUNT,按 TRADE_DT 在 [self.start_date, self.end_date] 范围内，
        每段长度由 delta_days 控制（单位：天），分段下载并增量写入同一个 pkl。
        """
        name = 'S_DQ_AMOUNT'
        save_path = os.path.join(config.data_raw_folder_path, name + '.pkl')

        # 一次建连接，循环复用
        dl_wind = Download_wind()

        # 依据 delta_days 切分 [start, end] 闭区间
        date_ranges = self.split_by_delta_days(self.start_date, self.end_date, delta_days)

        print(f"准备分 {len(date_ranges)} 段下载 {name}，delta_days={delta_days}")
        print(f"整体区间: [{self.start_date}, {self.end_date}]")
        # print(date_ranges)  # 如果想看具体切分结果，可以打开这一行

        for i, (sub_start, sub_end) in enumerate(date_ranges, start=1):
            sql = f"""
                SELECT S_INFO_WINDCODE,
                    TRADE_DT,
                    {name}
                FROM WIND.AShareEODPrices
                WHERE TRADE_DT >= {sub_start}
                AND TRADE_DT <= {sub_end}
            """

            print(f"[{i}/{len(date_ranges)}] 下载区间: [{sub_start}, {sub_end}] ...")
            sub_df = dl_wind.dl_general(sql)
            sub_df = self.drop_duplicated_with_tol(sub_df)
            

            if sub_df.empty:
                print(f"[{i}/{len(date_ranges)}] 该区间无数据，跳过。")
                continue

            # 按 ANN_DT 排序并写入（update_and_save_pkl_only_concat 是你之前的工具函数）
            ok = DataOs.update_and_save_pkl_only_concat(
                sub_df,
                save_path,
                "TRADE_DT"   # 现在按公告日排序
            )
            if not ok:
                print(f"[{i}/{len(date_ranges)}] 保存失败！")
            else:
                print(f"[{i}/{len(date_ranges)}] 保存成功，本段行数: {len(sub_df)}")

        # 可选：最后读出看一眼
        try:
            final_df = pd.read_pickle(save_path)
            # print("最终合并后的 DataFrame 预览：")
            # print(final_df.head())
            print(f"总行数: {len(final_df)}")
        except Exception as e:
            print(f"最终读取 {save_path} 失败: {e}")
    
    def S_VAL_PB_NEW_DLDnSAVE(self, delta_days: int = 30):
        """
        分段下载 S_VAL_PB_NEW,按 TRADE_DT 在 [self.start_date, self.end_date] 范围内，
        每段长度由 delta_days 控制（单位：天），分段下载并增量写入同一个 pkl。
        """
        name = 'S_VAL_PB_NEW'
        save_path = os.path.join(config.data_raw_folder_path, name + '.pkl')

        # 一次建连接，循环复用
        dl_wind = Download_wind()

        # 依据 delta_days 切分 [start, end] 闭区间
        date_ranges = self.split_by_delta_days(self.start_date, self.end_date, delta_days)

        print(f"准备分 {len(date_ranges)} 段下载 {name}，delta_days={delta_days}")
        print(f"整体区间: [{self.start_date}, {self.end_date}]")
        # print(date_ranges)  # 如果想看具体切分结果，可以打开这一行

        for i, (sub_start, sub_end) in enumerate(date_ranges, start=1):
            sql = f"""
                SELECT S_INFO_WINDCODE,
                    TRADE_DT,
                    {name}
                FROM WIND.AShareEODDerivativeIndicator
                WHERE TRADE_DT >= {sub_start}
                AND TRADE_DT <= {sub_end}
            """

            print(f"[{i}/{len(date_ranges)}] 下载区间: [{sub_start}, {sub_end}] ...")
            sub_df = dl_wind.dl_general(sql)
            sub_df = self.drop_duplicated_with_tol(sub_df)
            

            if sub_df.empty:
                print(f"[{i}/{len(date_ranges)}] 该区间无数据，跳过。")
                continue

            # 按 ANN_DT 排序并写入（update_and_save_pkl_only_concat 是你之前的工具函数）
            ok = DataOs.update_and_save_pkl_only_concat(
                sub_df,
                save_path,
                "TRADE_DT"   # 现在按公告日排序
            )
            if not ok:
                print(f"[{i}/{len(date_ranges)}] 保存失败！")
            else:
                print(f"[{i}/{len(date_ranges)}] 保存成功，本段行数: {len(sub_df)}")

        # 可选：最后读出看一眼
        try:
            final_df = pd.read_pickle(save_path)
            # print("最终合并后的 DataFrame 预览：")
            # print(final_df.head())
            print(f"总行数: {len(final_df)}")
        except Exception as e:
            print(f"最终读取 {save_path} 失败: {e}")
    
    def S_VAL_MV_DLDnSAVE(self, delta_days: int = 30):
        """
        分段下载 S_VAL_MV,按 TRADE_DT 在 [self.start_date, self.end_date] 范围内，
        每段长度由 delta_days 控制（单位：天），分段下载并增量写入同一个 pkl。
        """
        name = 'S_VAL_MV'
        save_path = os.path.join(config.data_raw_folder_path, name + '.pkl')

        # 一次建连接，循环复用
        dl_wind = Download_wind()

        # 依据 delta_days 切分 [start, end] 闭区间
        date_ranges = self.split_by_delta_days(self.start_date, self.end_date, delta_days)

        print(f"准备分 {len(date_ranges)} 段下载 {name}，delta_days={delta_days}")
        print(f"整体区间: [{self.start_date}, {self.end_date}]")
        # print(date_ranges)  # 如果想看具体切分结果，可以打开这一行

        for i, (sub_start, sub_end) in enumerate(date_ranges, start=1):
            sql = f"""
                SELECT S_INFO_WINDCODE,
                    TRADE_DT,
                    {name}
                FROM WIND.AShareEODDerivativeIndicator
                WHERE TRADE_DT >= {sub_start}
                AND TRADE_DT <= {sub_end}
            """

            print(f"[{i}/{len(date_ranges)}] 下载区间: [{sub_start}, {sub_end}] ...")
            sub_df = dl_wind.dl_general(sql)
            sub_df = self.drop_duplicated_with_tol(sub_df)
            

            if sub_df.empty:
                print(f"[{i}/{len(date_ranges)}] 该区间无数据，跳过。")
                continue

            # 按 ANN_DT 排序并写入（update_and_save_pkl_only_concat 是你之前的工具函数）
            ok = DataOs.update_and_save_pkl_only_concat(
                sub_df,
                save_path,
                "TRADE_DT"   # 现在按公告日排序
            )
            if not ok:
                print(f"[{i}/{len(date_ranges)}] 保存失败！")
            else:
                print(f"[{i}/{len(date_ranges)}] 保存成功，本段行数: {len(sub_df)}")

        # 可选：最后读出看一眼
        try:
            final_df = pd.read_pickle(save_path)
            # print("最终合并后的 DataFrame 预览：")
            # print(final_df.head())
            print(f"总行数: {len(final_df)}")
        except Exception as e:
            print(f"最终读取 {save_path} 失败: {e}")
    
    
    def EST_DLDnSAVE(self, name = 'NET_PROFIT',delta_days: int = 30):
        """
        分段下载 name,按 EST_DT 在 [self.start_date, self.end_date] 范围内，
        每段长度由 delta_days 控制（单位：天），分段下载并增量写入同一个 pkl。
        """
        save_path = os.path.join(config.data_raw_folder_path, name + '.pkl')

        # 一次建连接，循环复用
        dl_wind = Download_wind()

        # 依据 delta_days 切分 [start, end] 闭区间
        date_ranges = self.split_by_delta_days(self.start_date, self.end_date, delta_days)

        print(f"准备分 {len(date_ranges)} 段下载 {name}，delta_days={delta_days}")
        print(f"整体区间: [{self.start_date}, {self.end_date}]")
        # print(date_ranges)  # 如果想看具体切分结果，可以打开这一行

        for i, (sub_start, sub_end) in enumerate(date_ranges, start=1):
            sql = f"""
                SELECT S_INFO_WINDCODE,
                    EST_DT,ROLLING_TYPE,
                    {name}
                FROM WIND.AShareConsensusRollingData
                WHERE EST_DT >= {sub_start}
                AND EST_DT <= {sub_end}
            """

            print(f"[{i}/{len(date_ranges)}] 下载区间: [{sub_start}, {sub_end}] ...")
            sub_df = dl_wind.dl_general(sql)
            sub_df = self.drop_duplicated_with_tol(sub_df)
            

            if sub_df.empty:
                print(f"[{i}/{len(date_ranges)}] 该区间无数据，跳过。")
                continue

            # 按 EST_DT 排序并写入（update_and_save_pkl_only_concat 是你之前的工具函数）
            ok = DataOs.update_and_save_pkl_only_concat(
                sub_df,
                save_path,
                "EST_DT"   # 现在按公告日排序
            )
            if not ok:
                print(f"[{i}/{len(date_ranges)}] 保存失败！")
            else:
                print(f"[{i}/{len(date_ranges)}] 保存成功，本段行数: {len(sub_df)}")

        # 可选：最后读出看一眼
        try:
            final_df = pd.read_pickle(save_path)
            # print("最终合并后的 DataFrame 预览：")
            # print(final_df.head())
            print(f"总行数: {len(final_df)}")
        except Exception as e:
            print(f"最终读取 {save_path} 失败: {e}")
    
    
    
    
    
    @staticmethod
    def index_date_process():
        
        
        df = pd.read_pickle(config.data_path('S_DQ_AMOUNT')) 
        df_date = DataFrameTools.unique_column_as_df(df,'TRADE_DT','date')
        df_date['date'] = df_date['date'].apply(TimestampUtils.date_everything_2_date)
        df_date.to_pickle(config.Date_pkl_path)
        DataOs.save_sheet_2_excel(config.Date_excel_path,df_date)
        
        # df = pd.read_pickle(config.data_path('S_DQ_AMOUNT')) 
        df_code = DataFrameTools.unique_column_as_df(df,'S_INFO_WINDCODE','code')
        df_code.to_pickle(config.Index_pkl_path)
        DataOs.save_sheet_2_excel(config.Index_excel_path,df_code)
   
   
    def data_dedu(self):
        
        for name in self.data_list:
            path_temp = config.data_path(name)
            df = self.drop_duplicated_with_tol(pd.read_pickle(path_temp))
            df.to_pickle(path_temp)
   

    def main(self):
        
        # 研发费用
        self.RD_EXPENSE_DLDnSAVE()
        print('研发费用下载完毕')
        
        # 资产总计
        self.TOT_ASSETS_DLDnSAVE()
        print('资产总计下载完毕')
        
        # 扣费净利润
        self.NET_PROFIT_AFTER_DED_NR_LP_DLDnSAVE()
        print('扣费净利润下载完毕')
        
        # 归属于母公司的股东权益(MRQ)
        self.S_DFA_EQUITY_DLDnSAVE()
        self.TOT_SHRHLDR_EQY_EXCL_MIN_INT_DLDnSAVE()
        print('归属于母公司的股东权益下载完毕')
        
        # 成交金额
        self.S_DQ_AMOUNT_DLDnSAVE()
        print('成交金额下载完毕')
        
        # PB
        self.S_VAL_PB_NEW_DLDnSAVE()
        print('PB下载完毕')
        
        # 市值
        self.S_VAL_MV_DLDnSAVE()
        
        print('市值下载完毕!')
        
        # 一致预期数据
        self.EST_DLDnSAVE('NET_PROFIT') # 净利润
        self.EST_DLDnSAVE('EST_BPS') # 每股净资产
        self.EST_DLDnSAVE('EST_BASESHARE') # 预测基准股本综合值

        
        
        # # 去重 ,一般不再需要
        # self.data_dedu()
        
        
        # 进行所有股票标的获取
        self.index_date_process()
        
        print('全部下载完毕!')


class DataProcess:
    
    def __init__(self,start_date = '20160101',end_date = '20251120',if_save_excel = False):
        
        self.start_date = start_date
        self.end_date = end_date
        
        self.data_list = datalist
        self.col_list = col_list
        
        self.date_list = pd.read_pickle(config.Date_pkl_path)['date'].tolist()
        self.code_name_list = pd.read_pickle(config.Index_pkl_path)['code'].tolist()
        self.if_save_excel = if_save_excel
    
    @staticmethod
    def _add_threshold_stats(df: pd.DataFrame, t: float = 0) -> pd.DataFrame:
        """
        在 df 最左侧添加两列：
        1. '大于阈值t个数'：每一行中 > 阈值 t 的元素个数
        - 若 t == 0，则使用 > 1e-8
        - NaN 不参与“个数”统计（视为 False）
        - 无法比较的元素（TypeError 等）按 False 处理
        2. '大于阈值t占比'：上述个数 / 该行总列数（包括 NaN），保留两位小数 + 百分号

        index、原列顺序保持不变，只是在最前插入两列。
        """

        def _gt_safe(x, t):
            # NaN：不参与“个数”，视为 False
            if pd.isna(x):
                return False
            try:
                if t == 0:
                    return x > 1e-8
                else:
                    return x > t
            except TypeError:
                # 无法比较：按 False 处理
                return False

        data = df.copy()

        # ✅ 用 Series.map 替代 DataFrame.applymap，避免 FutureWarning
        cond = data.apply(lambda col: col.map(lambda x: _gt_safe(x, t)))

        # 每行：大于阈值的个数
        count_over = cond.sum(axis=1)

        # 分母：每行总列数（包含 NaN）
        total_cols = data.shape[1]
        ratio = count_over / total_cols

        # 百分比字符串
        ratio_pct = (ratio * 100).round(2).map(lambda x: f"{x:.2f}%")

        # 插入到最前面
        result = data.copy()
        result.insert(0, "大于阈值t个数", count_over)
        result.insert(1, "大于阈值t占比", ratio_pct)

        return result

    @staticmethod
    def _amount_long_to_wide(df: pd.DataFrame,index_name:str = 'TRADE_DT',col_name:str = 'S_INFO_WINDCODE' ,value_name:str = 'S_DQ_AMOUNT') -> pd.DataFrame:
        """
        输入 df 格式,必须含有如下三列
            index_name, col_name, value_name
        
        返回一个
        df
        """
        df = df.copy()

        # 1. TRADE_DT 转成日期格式（假设是形如 20160104 的字符串或整数）
        df[index_name] = pd.to_datetime(df[index_name], format="%Y%m%d").dt.date

        # 2. 透视成宽表
        # 如果 (TRADE_DT, S_INFO_WINDCODE) 唯一，可以用 pivot；
        # 如果可能有重复，用 pivot_table + aggfunc='sum' 或 'last'。
        wide = df.pivot_table(
            index=index_name,
            columns=col_name,
            values= value_name,
            aggfunc="last",   # 如果你确定没有重复行，可以换成 pivot 或把 aggfunc 改 'last'
        )

        # 3. 一般习惯按日期和代码排序一下（可选）
        wide = wide.sort_index()
        wide = wide.reindex(sorted(wide.columns), axis=1)

        return wide
    
    @staticmethod
    def _dedup_rd_expense_keep_earliest_with_diff(
        df: pd.DataFrame,
        name,
        tol_ratio: float = 0.01,  # 0.1% = 0.001
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        按 (REPORT_PERIOD, S_INFO_WINDCODE) 分组，对 name 做容差去重：

        对每个组 g：
        1. 若 len(g) == 1：
            - df_clean 中保留该行
            - 不进入 df_diff
        2. 若 len(g) > 1：
            - 看该组的 name 非 NaN 值：
                * 若非 NaN 个数 <= 1：
                    => 视为“值相同”
                    => df_clean 中只保留 ANN_DT 最小的那一行
                    => 不进入 df_diff
                * 若非 NaN 个数 >= 2：
                    - 计算组内整体跨度 (max - min) / max：
                        · 若 <= tol_ratio：
                            => 视为“值相同”
                            => df_clean 中只保留 ANN_DT 最小的那一行
                            => 不进入 df_diff
                        · 若 > tol_ratio：
                            => 视为“值不同（冲突组）”
                            => df_clean 中：只保留 ANN_DT 最小的那一行
                            => df_diff 中：放入“与基准值差异 > tol_ratio 的那些行”
                                （基准值取本组 ANN_DT 最早且 name 非 NaN 的那一行）

        返回:
            df_clean: 每个组只保留一行（ANN_DT 最小），且满足上述容差规则
            df_diff : 只包含“冲突组中 name 与基准值不同”的那些行
        """

        required_cols = {"ANN_DT", name, "REPORT_PERIOD", "S_INFO_WINDCODE"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"df 缺少必要列: {missing}")

        if df.empty:
            return df.copy(), df.copy()

        grp_keys = ["REPORT_PERIOD", "S_INFO_WINDCODE"]

        # 先整体按 group key + ANN_DT 排序，方便取“ANN_DT 最小的一行”
        df_sorted = df.sort_values(grp_keys + ["ANN_DT"]).copy()

        clean_list = []
        diff_list = []

        for _, g in df_sorted.groupby(grp_keys, sort=False):
            # 组内只有一行 -> 直接保留
            if len(g) == 1:
                clean_list.append(g)
                continue

            # 组内多行
            rd = g[name]
            rd_non_nan = rd.dropna()

            # 非 NaN 个数 <= 1：认为值“相同”，只保留 ANN_DT 最小那一行
            if rd_non_nan.size <= 1:
                clean_list.append(g.iloc[[0]])  # 已按 ANN_DT 排好
                continue

            # 有至少两个非 NaN：
            rd_max = rd_non_nan.max()
            rd_min = rd_non_nan.min()

            if rd_max == 0:
                rel_span = 0.0 if rd_min == 0 else np.inf
            else:
                rel_span = (rd_max - rd_min) / abs(rd_max)

            # 先默认：clean 里只保留 ANN_DT 最小那一行
            earliest_row = g.iloc[[0]]
            clean_list.append(earliest_row)

            # 组内整体跨度 <= 容差：视为相同，不需要 diff
            if rel_span <= tol_ratio:
                continue

            # ---- 冲突组：需要构造 df_diff ----
            # 基准行：本组 ANN_DT 最早且 RD_EXPENSE 非 NaN 的那一行
            g_non_nan = g[g[name].notna()].copy()
            if g_non_nan.empty:
                # 理论上不会，因为 rd_non_nan.size >= 2，但稳妥起见
                continue

            base_row_for_diff = g_non_nan.iloc[0]
            base_val = base_row_for_diff[name]

            # 对非 NaN 行逐个计算相对基准的差异
            if base_val == 0:
                denom = g_non_nan[name].abs().replace(0, np.nan)
                rel_diff_to_base = (g_non_nan[name] - base_val).abs() / denom
                rel_diff_to_base = rel_diff_to_base.fillna(0.0)
            else:
                rel_diff_to_base = (g_non_nan[name] - base_val).abs() / abs(base_val)

            # 与基准差异 > tol_ratio 的行视为“有问题的行”
            bad_mask = rel_diff_to_base > tol_ratio
            g_bad = g_non_nan[bad_mask]

            # 注意：基准行本身不会进 diff（它的 rel_diff_to_base == 0）
            if not g_bad.empty:
                diff_list.append(g_bad)

        # 汇总 clean / diff
        df_clean = (
            pd.concat(clean_list, axis=0)
            .sort_values(grp_keys + ["ANN_DT"])
            .reset_index(drop=True)
        )

        if diff_list:
            df_diff = (
                pd.concat(diff_list, axis=0)
                .sort_values(grp_keys + ["ANN_DT"])
                .reset_index(drop=True)
            )
        else:
            # 构造结构一致的空 df
            df_diff = df_sorted.head(0).copy()

        return df_clean, df_diff
    
    @staticmethod
    def _drop_nan_in_column(df: pd.DataFrame, name: str) -> pd.DataFrame:
        """
        输入：
            df   : 一个 DataFrame
            name : 列名
            
        功能：
            去除 df[name] 中为 NaN 的行，返回过滤后的 df

        返回：
            一个新的 DataFrame（不会修改原 df）
        """
        if name not in df.columns:
            raise ValueError(f"列 {name} 不存在于 df 中！")

        return df[df[name].notna()].copy()
    
    @staticmethod
    def _select_records_by_code(df: pd.DataFrame,name = 'RD_EXPENSE') -> pd.DataFrame:
        """
        输入：
            df: 包含列 ['ANN_DT', name, 'REPORT_PERIOD', 'S_INFO_WINDCODE']

        对每个 S_INFO_WINDCODE：
            1. 按 ANN_DT 升序，如果 ANN_DT 相同则按 REPORT_PERIOD 升序排序
            2. 对每个 ANN_DT，只保留 REPORT_PERIOD 最大的那一行
            3. 在按 ANN_DT 排好序的结果中，要求后一行的 REPORT_PERIOD 严格大于前一行，
            否则丢弃该行
        返回：
            满足条件的行组成的 DataFrame
        """

        def _process_one_code(g: pd.DataFrame) -> pd.DataFrame:
            # 1. 按 ANN_DT, REPORT_PERIOD 排序
            g = g.sort_values(["ANN_DT", "REPORT_PERIOD"])

            # 2. 每个 ANN_DT 只保留 REPORT_PERIOD 最大的那一行
            #    因为已经按 REPORT_PERIOD 升序，所以保留最后一条
            g = g.drop_duplicates(subset="ANN_DT", keep="last")

            # 3. 再按 ANN_DT 排一下（理论上已经是升序了，这里只是确保）
            g = g.sort_values("ANN_DT")

            # 4. 要求 REPORT_PERIOD 严格递增
            #    先把 REPORT_PERIOD 转成可比较的数值（如 20151231 -> int）
            rp = pd.to_numeric(g["REPORT_PERIOD"], errors="coerce")

            keep_flags = []
            last_rp = None
            for v in rp:
                if last_rp is None or v > last_rp:
                    keep_flags.append(True)
                    last_rp = v
                else:
                    keep_flags.append(False)

            return g.loc[np.array(keep_flags)]

        # 对每个 S_INFO_WINDCODE 分组处理，最后拼回一张表
        out = df.groupby("S_INFO_WINDCODE", group_keys=False).apply(_process_one_code)
        # 如果不想有多级索引，reset_index(drop=True)
        out = out.reset_index(drop=True)
        return out
    

    @staticmethod
    def _calc_quarter_delta(df, value_col="RD_EXPENSE"):
        """
        对每个 S_INFO_WINDCODE、每个年份内：
        1. 若前一季度有值：当前值 - 前一季度值
        2. 若前一季度无值/无该行，但当年更早季度有值：
        (当前值 - 最近一个“更早季度”的值) / 间隔的季度数
        3. 若当年之前都无值：当前值 / 当前是当年的第几个季度(1/2/3/4)
        结果写到新列 value_col + "_qdelta" 中，返回处理好的 df。
        """
        df = df.copy()

        # 转日期 + 排序
        df["REPORT_PERIOD"] = pd.to_datetime(df["REPORT_PERIOD"].astype(str))
        df = df.sort_values(["S_INFO_WINDCODE", "REPORT_PERIOD"])

        # 提取年、季度（3→1, 6→2, 9→3, 12→4）
        df["year"] = df["REPORT_PERIOD"].dt.year
        df["quarter"] = df["REPORT_PERIOD"].dt.month // 3

        def _per_code_year(g):
            """
            g: 单个 S_INFO_WINDCODE + year 的子 DataFrame（已按 REPORT_PERIOD 排序）
            """
            last_q = None     # 最近一个有值的季度号（1~4）
            last_v = None     # 最近一个有值的该列数值
            out = []

            for idx, row in g.iterrows():
                v = row[value_col]
                q = row["quarter"]

                # 当前季度自身没值，就直接 NaN，且不更新 last_q/last_v
                if pd.isna(v):
                    out.append(np.nan)
                    continue

                if last_q is None:
                    # 当年之前都无值： rule 3
                    # 当前季度数 q：1(3月)、2(6月)、3(9月)、4(12月)
                    res = v / q
                else:
                    gap = int(q - last_q)  # 与最近一次有值之间间隔了多少个季度

                    if gap <= 0:
                        # 同季度重复或乱序数据，简单退化成差值处理
                        res = v - last_v
                    elif gap == 1:
                        # 正常相邻季度： rule 1
                        res = v - last_v
                    else:
                        # 中间有缺失季度： rule 2
                        # 例如：Q1 有值，Q2 无值，Q3 有值 -> (Q3 - Q1) / 2
                        res = (v - last_v) / gap

                out.append(res)

                # 只有当前季度有数值，才更新“最近一次有值”的记录
                last_q = q
                last_v = v

            return pd.Series(out, index=g.index)

        # 按代码 + 年分别处理
        df[value_col + "_qdelta"] = (
            df.groupby(["S_INFO_WINDCODE", "year"], group_keys=False)
            .apply(_per_code_year)
        )

        # 清理辅助列
        df = df.drop(columns=["year", "quarter"])

        return df

    @staticmethod
    def _fill_to_next_value(df: pd.DataFrame,date_col_name = "ANN_DT") -> pd.DataFrame:
        """
        对每一列按日期向后填充（前向填充），直到遇到新的非 NaN 值。
        保留输入的行列结构不变。
        """
        df = df.copy()

        # 如果 ANN_DT 是普通列，先设成索引（如果已经是索引，可跳过这一段）
        if date_col_name in df.columns:
            df[date_col_name] = pd.to_datetime(df[date_col_name])
            df = df.set_index(date_col_name)

        # 按日期排序（保险起见）
        df = df.sort_index()

        # 关键一步：前向填充
        df_filled = df.ffill()

        return df_filled
    
    @staticmethod
    def _fill_to_next_value_by_permit(df: pd.DataFrame, permit_days: int | None = None) -> pd.DataFrame:
        """
        index 已经是日期（DatetimeIndex）
        只在往前 permit_days 天内有真实值时才填充；窗口内无真实观测就不填充。
        填充值不会被当作“真实观测”继续滚动传递。
        """
        if df.empty:
            return df.copy()

        df = df.copy()

        # 确保 index 是 DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        df = df.sort_index()

        # 1. 普通前向填充，得到“候选填充值”
        df_filled = df.ffill()

        # 若不限制天数，就直接返回普通 ffill 结果
        if permit_days is None:
            return df_filled

        # 2. 构造日期矩阵，每列都是 index
        date_index = df.index.to_series()
        date_mat = pd.DataFrame(
            np.tile(date_index.values, (df.shape[1], 1)).T,
            index=df.index,
            columns=df.columns,
        )

        # 3. 原始真实观测位置
        real_mask = df.notna()

        # 4. 真实观测用自身日期，否则 NaT，然后按列 ffill 得到“最近一次真实观测日期”
        last_real_date = date_mat.where(real_mask).ffill()

        # 5. 计算距离最近真实观测的天数（DataFrame 级别运算，不能用 .dt）
        delta = date_mat - last_real_date          # timedelta64[ns] DataFrame
        days_since_last_real = delta / np.timedelta64(1, "D")  # float，单位天

        # 6. 超过 permit_days 的位置不允许填充 → 置 NaN
        over_limit = days_since_last_real > permit_days
        df_filled[over_limit] = np.nan

        return df_filled
    
    def eazy_data_get(self,name='S_DQ_AMOUNT'):
        
        df_amount = pd.read_pickle(config.data_path(name))
        
        df_out_amount = self._amount_long_to_wide(df_amount,value_name = name)
        # df_out_amount = self._df_to_A_formatted_df(df_amount)
        
        print(df_out_amount)
    
        
        df_out_amount.to_pickle(config.data_path(name,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path(name,'processed','xlsx'),df_out_amount,write_index=True)
        
    def format_date_get(self, name: str = "S_DFA_EQUITY",index_name = 'TRADE_DT',col_name = 'S_INFO_WINDCODE') -> pd.DataFrame:
        # 1. 读取长表
        df_amount = pd.read_pickle(config.data_path(name))

        # 2. 长表 -> 宽表
        df_out_amount = self._amount_long_to_wide(df_amount, value_name=name,index_name=index_name,col_name=col_name)

        # 3. 确保 index 类型和 self.data_list 一致（如果 self.date_list 是 date，就转成 date）
        #    如果本来就是 date，就可以省这一步
        # df_out_amount.index = [
        #     TimestampUtils.date_everything_2_date(d) for d in df_out_amount.index
        # ]

        # target_index = [
        #     TimestampUtils.date_everything_2_date(d) for d in self.date_list
        # ]
        target_index = self.date_list
        
        target_columns = list(self.code_name_list)
        
        # print(df_out_amount)

        # 4. 直接对齐到 {target_index × target_columns} 网格
        #    多余的行/列会被丢掉，不足的补 NaN
        df_out_amount = df_out_amount.reindex(
            index=target_index,
            columns=target_columns,
        )
        
        df_out_amount.to_pickle(config.data_path(name,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path(name,'processed','xlsx'),self._add_threshold_stats(df_out_amount),write_index=True)

        return df_out_amount
    
    
    def format_date_get_input_df(self,df_amount, name: str = "S_DFA_EQUITY",index_name = 'TRADE_DT',col_name = 'S_INFO_WINDCODE',if_save = True) -> pd.DataFrame:
        
        # # 1. 读取长表 
        # df_amount = pd.read_pickle(config.data_path(name))

        # 2. 长表 -> 宽表
        df_out_amount = self._amount_long_to_wide(df_amount, value_name=name,index_name=index_name,col_name=col_name)

        # 3. 确保 index 类型和 self.data_list 一致（如果 self.date_list 是 date，就转成 date）
        #    如果本来就是 date，就可以省这一步
        # df_out_amount.index = [
        #     TimestampUtils.date_everything_2_date(d) for d in df_out_amount.index
        # ]

        # target_index = [
        #     TimestampUtils.date_everything_2_date(d) for d in self.date_list
        # ]
        target_index = self.date_list
        
        target_columns = list(self.code_name_list)
        
        # print(df_out_amount)

        # 4. 直接对齐到 {target_index × target_columns} 网格
        #    多余的行/列会被丢掉，不足的补 NaN
        df_out_amount = df_out_amount.reindex(
            index=target_index,
            columns=target_columns,
        )
        
        if if_save:
            df_out_amount.to_pickle(config.data_path(name,'processed'))
            if self.if_save_excel:
                DataOs.save_sheet_2_excel(config.data_path(name,'processed','xlsx'),self._add_threshold_stats(df_out_amount),write_index=True)

        return df_out_amount
    
    
    
    def Q_data_1(self,name = 'RD_EXPENSE'):
        
        df_amount = pd.read_pickle(config.data_path(name))
        
        
        df_out_amount,df_error = self._dedup_rd_expense_keep_earliest_with_diff(df_amount,name)
        df_out_amount = self._drop_nan_in_column(df_out_amount,name)
        
        if df_error.shape[0] >=1:
            print(name + '出现重复且不同数据！')
            # print(df_error)
            if self.if_save_excel:
                DataOs.save_sheet_2_excel(config.data_path(name + '_error','processed','xlsx'),df_out_amount,write_index=True)
        else:
            print(name + '数据无重复')
            
        df_out_amount = self._select_records_by_code(df_out_amount)
        
        df_out_amount.to_pickle(config.data_path(name + '_dedu' ,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path(name + '_dedu','processed','xlsx'),df_out_amount,write_index=True)
    
    
    def Q_delta_process(self,name = 'RD_EXPENSE'):
        
        df_amount = pd.read_pickle(config.data_path(name + '_dedu' ,'processed'))
        
        df_out_amount = self._calc_quarter_delta(df_amount,name)
        
        
        
        df_out_amount.to_pickle(config.data_path(name + '_delta' ,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path(name + '_delta','processed','xlsx'),df_out_amount,write_index=True)
        
        df_out = self.format_date_get_input_df(df_out_amount,index_name='ANN_DT',name=name + '_qdelta',if_save= False)
        
        df_out.to_pickle(config.data_path(name  ,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path(name,'processed','xlsx'),df_out,write_index=True)
        
    
    def Q_fill_nan(self,name):
        
        
        df_amount = pd.read_pickle(config.data_path(name,'processed'))
        
        df_out = self._fill_to_next_value(df_amount)
        
        df_out.to_pickle(config.data_path(name  ,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path(name,'processed','xlsx'),self._add_threshold_stats(df_out),write_index=True)
    
    
    def ROE_cal(self):
        
        df_NET_PROFIT = pd.read_pickle(config.data_path('NET_PROFIT_AFTER_DED_NR_LP','processed'))
        df_MRQ = pd.read_pickle(config.data_path('TOT_SHRHLDR_EQY_EXCL_MIN_INT','processed'))
        
        FCT = FactorCalTools()
        df_NET_PROFIT_TTM = FCT.rolling_mean(df_NET_PROFIT,255)
        df_MRQ_TTM = FCT.rolling_mean(df_MRQ,255)
        
        df_ROE = FCT.div_safe(df_NET_PROFIT,df_MRQ)
        df_ROE_TTM = FCT.div_safe(df_NET_PROFIT_TTM,df_MRQ_TTM)
        
        
        df_ROE.to_pickle(config.data_path('ROE' ,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('ROE','processed','xlsx'),self._add_threshold_stats(df_ROE),write_index=True)
        
        df_ROE_TTM.to_pickle(config.data_path('ROE_TTM' ,'processed'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('ROE_TTM','processed','xlsx'),self._add_threshold_stats(df_ROE_TTM),write_index=True)
        
    
    
    def EST_cal(self,name = 'NET_PROFIT',want_year = [0,1],permit_days = 65):
        
        df_amount = pd.read_pickle(config.data_path(name))
        
        for i in want_year:
            str_i = str(i)
            df = df_amount.loc[df_amount['ROLLING_TYPE'] == 'FY' + str_i ].drop(columns=['ROLLING_TYPE'])
            
            df = self.format_date_get_input_df(df,name = name,index_name='EST_DT',if_save=False)
            df = self._fill_to_next_value_by_permit(df,permit_days)
            
            df.to_pickle(config.data_path(name + '_EST_' + str_i,'processed'))
            if self.if_save_excel:
                DataOs.save_sheet_2_excel(config.data_path(name + '_EST_' + str_i,'processed','xlsx'),self._add_threshold_stats(df,t = - np.inf),write_index=True)

        return df_amount
    
    def EST_ROE(self,name):
        
        df0 = pd.read_pickle(config.data_path(name + '_EST_' + '0','processed'))
        df1 = pd.read_pickle(config.data_path(name + '_EST_' + '1','processed'))
        
        
        
        pass
            
        
        
        
        
        
        
    def main(self):
        
        
        
        # # # 成交金额处理
        # self.format_date_get('S_DQ_AMOUNT')
        
        # # # 归属于母公司的股东权益(MRQ) 处理
        # self.format_date_get('S_DFA_EQUITY')
        
        # # # PB 处理
        # self.format_date_get('S_VAL_PB_NEW')
        
        # # # 市值 处理
        # self.format_date_get('S_VAL_MV')
        
        
        # # 研发费用
        # self.Q_data_1('RD_EXPENSE')
        # self.Q_delta_process('RD_EXPENSE')
        # self.Q_fill_nan('RD_EXPENSE')
        
        
        # # 资产总计
        # self.Q_data_1('TOT_ASSETS')
        # self.format_date_get_input_df(df_amount=pd.read_pickle(config.data_path('TOT_ASSETS_dedu' ,'processed')),name='TOT_ASSETS',index_name='ANN_DT')
        # self.Q_fill_nan('TOT_ASSETS')
        
        # # 股东权益合计(不含少数股东权益) 处理
        # self.Q_data_1('TOT_SHRHLDR_EQY_EXCL_MIN_INT')
        # self.format_date_get_input_df(df_amount=pd.read_pickle(config.data_path('TOT_SHRHLDR_EQY_EXCL_MIN_INT_dedu' ,'processed')),name='TOT_SHRHLDR_EQY_EXCL_MIN_INT',index_name='ANN_DT')
        # self.Q_fill_nan('TOT_SHRHLDR_EQY_EXCL_MIN_INT')
        
        
        # # 扣费净利润
        # self.Q_data_1('NET_PROFIT_AFTER_DED_NR_LP')
        # self.Q_delta_process('NET_PROFIT_AFTER_DED_NR_LP')
        # self.Q_fill_nan('NET_PROFIT_AFTER_DED_NR_LP')
        
        # # ROE & ROE_TTM
        # self.ROE_cal()
        
        
        # 一致预期数据部分
        # 净利润  每股净资产   预测基准股本综合值
        namelist = ['NET_PROFIT','EST_BPS','EST_BASESHARE']
        want_year = [0,1]
        permit_days = 92
        for name_temp in namelist:
            # self.EST_cal(name_temp,want_year,permit_days)
            # 具体出值
            self.EST_ROE(name_temp)
            
            
            
            
            
        print('DataProcess MAIN FINISHED!')
        
    

class IndexProcess:
    
    def __init__(self,start_date = '20160101',end_date = '20251120',blacklist = [],only_generate_method_number = 1,if_save_excel = False):
    
        self.start_date = start_date
        self.end_date = end_date
        
        self.data_list = datalist
        self.col_list = col_list
        
        self.date_list = pd.read_pickle(config.Date_pkl_path)['date'].tolist()
        self.code_name_list = pd.read_pickle(config.Index_pkl_path)['code'].tolist()
        self.blacklist = blacklist
        
        
        
        
        ogm = only_generate_method_number
        if isinstance(ogm, list):
            self.only_generate_method_number = [int(i) for i in ogm]
        elif isinstance(ogm, (int, float, str)):
            # 数字或字符串都包一层 list
            ogm = int(ogm)
            self.only_generate_method_number = [ogm]
            
        self.if_save_excel = if_save_excel

    
    
    @staticmethod
    def _add_threshold_stats(df: pd.DataFrame, t: float = 0) -> pd.DataFrame:
        """
        在 df 最左侧添加两列：
        1. '大于阈值t个数'：每一行中 > 阈值 t 的元素个数
        - 若 t == 0，则使用 > 1e-8
        - NaN 不参与“个数”统计（视为 False）
        - 无法比较的元素（TypeError 等）按 False 处理
        2. '大于阈值t占比'：上述个数 / 该行总列数（包括 NaN），保留两位小数 + 百分号

        index、原列顺序保持不变，只是在最前插入两列。
        """

        def _gt_safe(x, t):
            # NaN：不参与“个数”，视为 False
            if pd.isna(x):
                return False
            try:
                if t == 0:
                    return x > 1e-8
                else:
                    return x > t
            except TypeError:
                # 无法比较：按 False 处理
                return False

        data = df.copy()

        # ✅ 用 Series.map 替代 DataFrame.applymap，避免 FutureWarning
        cond = data.apply(lambda col: col.map(lambda x: _gt_safe(x, t)))

        # 每行：大于阈值的个数
        count_over = cond.sum(axis=1)

        # 分母：每行总列数（包含 NaN）
        total_cols = data.shape[1]
        ratio = count_over / total_cols

        # 百分比字符串
        ratio_pct = (ratio * 100).round(2).map(lambda x: f"{x:.2f}%")

        # 插入到最前面
        result = data.copy()
        result.insert(0, "大于阈值t个数", count_over)
        result.insert(1, "大于阈值t占比", ratio_pct)

        return result
    
    @staticmethod
    def _drop_bottom_percent_to_mask(df: pd.DataFrame, percent: float) -> pd.DataFrame:
        """
        输入:
            df: index 是日期, columns 是股票代码, 值为某个指标
            percent: 0~1, 每一行希望删去的“尾部比例”（按数值从小到大）

        输出:
            mask_df: 与 df 同形状的 0/1 DataFrame, 0 表示被删去, 1 表示保留
        """
        if not (0 <= percent <= 1):
            raise ValueError("percent 必须在 [0, 1] 之间")

        def _handle_row(row: pd.Series) -> pd.Series:
            n_cols = row.size

            # 本行目标删去数量（按总列数算）
            target_del = int(np.floor(percent * n_cols))

            # 初始 mask：全 1（都保留）
            mask = pd.Series(1, index=row.index, dtype=int)

            # 1) 先删 NaN
            nan_mask = row.isna()
            nan_count = int(nan_mask.sum())
            mask[nan_mask] = 0  # 删掉所有 NaN

            # 2) 判断 NaN 数量是否已经超过比例
            if target_del <= nan_count:
                # NaN 已经够多了，不再额外删票
                return mask

            # 3) 需要额外删掉的数量
            extra_to_del = target_del - nan_count
            if extra_to_del <= 0:
                return mask

            # 在非 NaN 的票里，按数值从小到大选出 extra_to_del 个删掉
            valid = row[~nan_mask]
            if extra_to_del > len(valid):
                extra_to_del = len(valid)

            if extra_to_del > 0:
                # nsmallest: 最小的值（尾部）
                to_del_index = valid.nsmallest(extra_to_del).index
                mask[to_del_index] = 0

            return mask

        mask_df = df.apply(_handle_row, axis=1)
        # 保证是 int 型 0/1
        mask_df = mask_df.astype(int)

        return mask_df

    
    @staticmethod
    def _drop_given_percent_to_mask(
        df: pd.DataFrame,
        percent_low: float,
        percent_high: float,
        ascending: bool = True,
    ) -> pd.DataFrame:
        """
        输入:
            df: index 是日期, columns 是股票代码, 值为某个指标
            percent_low:  下界比例, [0,1] 之间, 表示删除区间的起点百分位
            percent_high: 上界比例, [0,1] 之间, 表示删除区间的终点百分位
                        删除的是区间 [percent_low, percent_high) 内的部分
            ascending: True  -> 按从小到大排序再按区间删除
                    False -> 按从大到小排序再按区间删除

        说明:
            - 对每一行:
                1) 所有 NaN 直接记为 0 (删除)
                2) 在非 NaN 的票中, 按 ascending 排序
                3) 按比例区间 [percent_low, percent_high) 选出对应那一段并置 0
            - percent_low, percent_high 作用在“非 NaN 数量”上
            比如某行有效票数 M, 则删除
                排名位置 [ floor(M*percent_low) : floor(M*percent_high) )
            - 返回与 df 同形状的 0/1 DataFrame, 0 表示被删, 1 表示保留
        """
        # 合法性检查
        if not (0.0 <= percent_low <= 1.0 and 0.0 <= percent_high <= 1.0):
            raise ValueError("percent_low 和 percent_high 必须在 [0, 1] 之间")
        if percent_low > percent_high:
            raise ValueError("percent_low 不能大于 percent_high")

        def _handle_row(row: pd.Series) -> pd.Series:
            # 初始 mask 全 1
            mask = pd.Series(1, index=row.index, dtype=int)

            # 先删 NaN
            nan_mask = row.isna()
            mask[nan_mask] = 0

            # 非 NaN 的票
            valid = row[~nan_mask]
            if valid.empty:
                # 这一行全是 NaN，直接返回
                return mask

            m = len(valid)
            # 根据比例计算在排序后的删去区间 [start_idx, end_idx)
            start_idx = int(np.floor(percent_low * m))
            end_idx = int(np.floor(percent_high * m))

            # 如果区间为空, 不额外删
            if end_idx <= start_idx:
                return mask

            # 按指定方向排序
            valid_sorted = valid.sort_values(ascending=ascending)

            # 按区间选出要删的 index
            to_del_index = valid_sorted.iloc[start_idx:end_idx].index
            mask[to_del_index] = 0

            return mask

        mask_df = df.apply(_handle_row, axis=1)
        mask_df = mask_df.astype(int)
        return mask_df

    
    @staticmethod
    def _select_topk_per_row(
        df: pd.DataFrame,
        k: int,
        ascending: bool = False,
        not_want_list=None,
        not_want_suffix=None,
    ) -> pd.DataFrame:
        """
        输入:
            df: index 为日期, columns 为股票代码
            k: 每行希望保留的固定数量（非 NaN 数据中选）
            ascending: False = 按从大到小选前 k 个（默认）
                    True  = 按从小到大选前 k 个
            not_want_list: 可选，list，如 ['920832.BJ']。
                        若排序靠前的标的在此列表中，则跳过并向后顺延。
            not_want_suffix: 可选，str 或 list。
                        只要列名(股票代码)以其中任一后缀结尾，则跳过并向后顺延。
                        例如：'BJ' 或 ['BJ', 'SH']，则 '920832.BJ'、'600000.SH' 都会被排除。

        输出:
            mask_df: 与 df 同形状的 0/1 DataFrame
                    1 表示该行该股票被保留, 0 表示未保留或 NaN
        """
        if k <= 0:
            # 不保留任何票, 全 0
            return pd.DataFrame(0, index=df.index, columns=df.columns, dtype=int)

        # 统一处理 not_want_list
        if not_want_list is None:
            not_want_set = set()
        else:
            not_want_set = {str(x) for x in not_want_list}

        # 统一处理 not_want_suffix
        if not_want_suffix is None:
            suffix_set = set()
        else:
            if isinstance(not_want_suffix, str):
                suffix_set = {not_want_suffix}
            else:
                suffix_set = {str(x) for x in not_want_suffix}

        def _is_forbidden_code(code) -> bool:
            """
            判断某个列名（股票代码）是否需要被排除：
            1) 在 not_want_list 中
            2) 以 not_want_suffix 列表中的任一后缀结尾
            """
            s = str(code)

            if s in not_want_set:
                return True

            if suffix_set:
                # 只要以任一后缀结尾就排除
                for suf in suffix_set:
                    if s.endswith(suf):
                        return True

            return False

        def _handle_row(row: pd.Series) -> pd.Series:
            # 初始 mask 全 0
            mask = pd.Series(0, index=row.index, dtype=int)

            # 非 NaN 的股票
            valid = row.dropna()
            if valid.empty:
                return mask

            # 按大小排序
            valid_sorted = valid.sort_values(ascending=ascending)

            # 从前往后扫，遇到不想要的(单票 or 后缀)就跳过，直到选到 k 只或耗尽
            selected = []
            for code in valid_sorted.index:
                if _is_forbidden_code(code):
                    continue
                selected.append(code)
                if len(selected) >= k:
                    break

            if not selected:
                return mask

            mask[selected] = 1
            return mask

        mask_df = df.apply(_handle_row, axis=1)
        return mask_df

    @staticmethod
    def _select_by_threshold(df: pd.DataFrame,
                        threshold: float,
                        mode: str = "ge") -> pd.DataFrame:
        """
        根据阈值逐行筛选，返回 0/1 mask df（与原 df 同形状）。

        参数
        ----
        df : DataFrame
            index 为日期，columns 为股票代码。
        threshold : float
            阈值。
        mode : str
            "ge" : 保留 >= threshold 的值（其余删掉）
            "le" : 保留 <= threshold 的值（其余删掉）

        返回
        ----
        mask_df : DataFrame
            0/1 的 DataFrame，1 表示保留，0 表示删除或原来就是 NaN。
        """
        if mode not in {"ge", "le"}:
            raise ValueError("mode 只能是 'ge' 或 'le'")

        # 与原 df 同形状的布尔矩阵
        if mode == "ge":
            cond = df >= threshold
        else:  # "le"
            cond = df <= threshold

        # NaN 视为不满足条件（False）
        cond = cond & df.notna()

        # 转成 0/1
        mask_df = cond.astype(int)
        return mask_df
    
    
    def liquity_check(self):
        
        FCT = FactorCalTools()
        
        df_liq = pd.read_pickle(config.data_path('S_DQ_AMOUNT','processed'))
        df_liq = FCT.rolling_mean(df_liq,255)
        
        # df_out = self._drop_bottom_percent_to_mask(df_liq,0.2)
        df_out = self._drop_given_percent_to_mask(df_liq,0.0,0.2,ascending=True)
        
        df_out.to_pickle(config.data_path('liquity','final'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('liquity','final','xlsx'),self._add_threshold_stats(df_out),write_index=True)
        
    def research_expense_check(self):
        
        FCT = FactorCalTools()
        
        df_res_exp = pd.read_pickle(config.data_path('RD_EXPENSE','processed'))
        df_asset = pd.read_pickle(config.data_path('TOT_ASSETS','processed'))
        df_res_exp_ratio = FCT.div_safe(df_res_exp,df_asset)
        
        df_out = self._drop_bottom_percent_to_mask(df_res_exp_ratio,0.5)
        
        df_out.to_pickle(config.data_path('research_expense','final'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('research_expense','final','xlsx'),self._add_threshold_stats(df_out),write_index=True)
        
    def ROE_and_PB(self):
        
        
        df_ROE = pd.read_pickle(config.data_path('ROE','processed'))
        df_PB = pd.read_pickle(config.data_path('S_VAL_PB_NEW','processed'))
        
        df_out = self._drop_given_percent_to_mask(df_ROE,0,0.5)
        df_out = df_out * self._drop_given_percent_to_mask(df_PB,0.0,0.05)
        df_out = df_out * self._drop_given_percent_to_mask(df_PB,0.25,1.00)
        
        df_out.to_pickle(config.data_path('ROE_PB','final'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('ROE_PB','final','xlsx'),self._add_threshold_stats(df_out),write_index=True)
    
    def ROE_DELETE_minus(self):
        
        df_ROE = pd.read_pickle(config.data_path('ROE','processed'))
        df_ROE_TTM = pd.read_pickle(config.data_path('ROE_TTM','processed'))
        
        
        
        df_out = self._select_by_threshold(df_ROE,threshold=0.0)
        df_out = df_out * self._select_by_threshold(df_ROE_TTM,threshold=0.0)
        
        df_out.to_pickle(config.data_path('ROE_and_ROETTM_positive','final'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('ROE_and_ROETTM_positive','final','xlsx'),self._add_threshold_stats(df_out),write_index=True)
    
    
    def final(self):
        '从剩余证券中，选取ROE(TTM)最大的50只证券作为指数样本。'
        
        # df_ROE_TTM = pd.read_pickle(config.data_path('ROE_TTM','processed'))
        
        df_liquity = pd.read_pickle(config.data_path('liquity','final'))
        df_research_expense = pd.read_pickle(config.data_path('research_expense','final'))
        df_ROE_PB = pd.read_pickle(config.data_path('ROE_PB','final'))
        df_ROE_positive = pd.read_pickle(config.data_path('ROE_and_ROETTM_positive','final'))
        
        df_pool = df_liquity * df_research_expense * df_ROE_PB * df_ROE_positive
        
        def keep_gt_half(df: pd.DataFrame) -> pd.DataFrame:
            """
            对 df 中所有数值列：
            - 保留 > 0.5 的值
            - 其余（<= 0.5 的值）置为 NaN
            非数值列保持不变。
            """
            df = df.copy()  # 避免原地修改

            # 只选择数值类型的列，避免对字符串等列出错
            num_cols = df.select_dtypes(include="number").columns

            # 对数值列做筛选：满足 > 0.5 保留，否则设为 NaN
            df[num_cols] = df[num_cols].where(df[num_cols] > 0.5, np.nan)

            return df
        
        df_pool = keep_gt_half(df_pool)
        
        df_pool.to_pickle(config.data_path('pool','final'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(config.data_path('pool','final','xlsx'),self._add_threshold_stats(df_pool),write_index=True)
        DataOs.save_sheet_2_excel(config.data_path('pool','final','xlsx'),self._add_threshold_stats(df_pool),write_index=True)
        
    def final_select_1(self):
        '从剩余证券中，选取ROE(TTM)最大的50只证券作为指数样本。'
        
        
        df_pool = pd.read_pickle(config.data_path('pool','final'))
        df_pool = df_pool.replace(0, np.nan)
        
        df_ROE_TTM = pd.read_pickle(config.data_path('ROE_TTM','processed'))
        df_v = df_ROE_TTM * df_pool
        
        df_out = self._select_topk_per_row(df_v,50,not_want_list=self.blacklist,not_want_suffix=self.blacklist)
        
        df_out.to_pickle(os.path.join(config.output_folder_path,'Value_Index_1.pkl'))
        if self.if_save_excel:
            DataOs.save_sheet_2_excel(os.path.join(config.output_folder_path,'Value_Index_1.xlsx'),self._add_threshold_stats(df_out),write_index=True)
    
    def final_select_3(self,QoQ_day = 75):
        '从剩余证券中，选取ROE(TTM)最大的50只证券作为指数样本。'
        
        
        df_pool = pd.read_pickle(config.data_path('pool','final'))
        df_pool = df_pool.replace(0, np.nan)
        
        df_ROE_TTM = pd.read_pickle(config.data_path('ROE_TTM','processed'))
        
        df_ROE_TTM_qoq_diff = df_ROE_TTM.sort_index().diff(QoQ_day)
        
        df_v = df_ROE_TTM_qoq_diff * df_pool
        
        df_out = self._select_topk_per_row(df_v,50,not_want_list=self.blacklist,not_want_suffix=self.blacklist)
        
        df_out.to_pickle(os.path.join(config.output_folder_path,'Value_Index_3.pkl'))
        
        # if self.if_save_excel:
        #     DataOs.save_sheet_2_excel(os.path.join(config.output_folder_path,'Value_Index_2.xlsx'),self._add_threshold_stats(df_out),write_index=True)
        DataOs.save_sheet_2_excel(os.path.join(config.output_folder_path,'Value_Index_3.xlsx'),self._add_threshold_stats(df_out),write_index=True)
    
    
    
    
    def main(self):
        
        # # 流动性筛选
        # self.liquity_check()
        
        # # 研发投入筛选
        # self.research_expense_check()
        
        # # 盈利与估值筛选 
        # self.ROE_and_PB()
        
        # # 负向剔除
        # self.ROE_DELETE_minus()
        
        # # 完成股票池建立
        # self.final()
        
        
        # 最终筛选
        for num in self.only_generate_method_number:
            getattr(self, f"final_select_{num}")()
        # self.final_select_n()
        
        print('IndexProcess MAIN FINISHED!')


class Index2Weight:
    
    def __init__(self,start_date = '20160101',end_date = '20251120',change_month_list = [2, 5, 8, 11],only_generate_method_number = 1,weight :str = 'equal'):
        
        '''
        weight :str = 'equal' or 'size' 表示仓位是等权还是依据市值分权重
        '''
        self.start_date = start_date
        self.end_date = end_date
        
        self.data_list = datalist
        self.col_list = col_list
        
        self.date_list = pd.read_pickle(config.Date_pkl_path)['date'].tolist()
        self.code_name_list = pd.read_pickle(config.Index_pkl_path)['code'].tolist()
        
        self.change_month_list = change_month_list
        
        ogm = only_generate_method_number
        if isinstance(ogm, list):
            self.only_generate_method_number = [int(i) for i in ogm]
        elif isinstance(ogm, (int, float, str)):
            # 数字或字符串都包一层 list
            ogm = int(ogm)
            self.only_generate_method_number = [ogm]
        
        if 'size' in weight:
            self.weight = 'size'
        elif 'equal' in weight:
            self.weight = 'equal'
        else:
            print('权重参数异常，默认等权')
            self.weight = 'equal'
        
    @staticmethod
    def gen_rebalance_df(df: pd.DataFrame,
                        month_list = [1,2,3,4,5,6,7,8,9,10,11,12],
                        startdate: str = '20200101') -> pd.DataFrame:
        """
        从 0/1 持仓矩阵生成调仓明细表。

        参数：
            df : index 为日期，columns 为股票代码，值为 0/1
            month_list : 需要调仓的月份列表，例如 [2, 5, 9, 11]
            startdate : 最早开始日期，字符串，如 '20200101'

        返回：
            result_df : DataFrame，4 列：
                调整日期, 证券代码, 持仓权重, 是否融资融券
        """
        # 确保 index 为 Timestamp
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # 过滤 startdate 之后
        start_ts = pd.to_datetime(startdate)
        df_sub = df[df.index >= start_ts].sort_index()

        # 只保留指定月份 & 每月 15 号（含）之后的行
        mask_month = df_sub.index.month.isin(month_list)
        mask_day = df_sub.index.day >= 15
        df_candidate = df_sub[mask_month & mask_day]

        if df_candidate.empty:
            # 没有任何调仓日，返回空表
            return pd.DataFrame(columns=["调整日期", "证券代码", "持仓权重", "是否融资融券"])

        # 对每个 year-month 只取“第一行”
        periods = df_candidate.index.to_period("M")
        first_mask = ~periods.duplicated()  # 每个 period 只保留第一条
        adjust_dates = df_candidate.index[first_mask]

        records = []
        for dt in adjust_dates:
            row = df_sub.loc[dt]

            # 找出值为 1 的股票
            ones = row[row == 1]
            if ones.empty:
                continue  # 该调仓日没有持仓，跳过

            n = len(ones)
            weight = 1.0 / n

            for code in ones.index:
                records.append({
                    "调整日期": dt,        # 如需写成字符串可用 dt.strftime('%Y%m%d')
                    "证券代码": code,
                    "持仓权重": weight,
                    "是否融资融券": ""     # 留空
                })

        result_df = pd.DataFrame(records,
                                columns=["调整日期", "证券代码", "持仓权重", "是否融资融券"])
        return result_df

    @staticmethod
    def gen_rebalance_df_by_weight_df(
        pos_df: pd.DataFrame,
        mktcap_df: pd.DataFrame,
        month_list = [1,2,3,4,5,6,7,8,9,10,11,12],
        startdate: str = '20200101'
    ) -> pd.DataFrame:
        """
        从 0/1 持仓矩阵生成调仓明细表（市值加权+鲁棒处理）。

        参数：
            pos_df   : index 为日期，columns 为股票代码，值为 0/1（是否持有）
            mktcap_df: 与 pos_df 形状相同，index/columns 对应，同一单元格为该日该股市值
            month_list : 需要调仓的月份列表，例如 [2, 5, 9, 11]
            startdate : 最早开始日期，字符串，如 '20200101'

        返回：
            result_df : DataFrame，4 列：
                调整日期, 证券代码, 持仓权重, 是否融资融券
        """
        # --- 1. 复制并确保 index 为 Timestamp ---
        pos_df = pos_df.copy()
        mktcap_df = mktcap_df.copy()

        if not isinstance(pos_df.index, pd.DatetimeIndex):
            pos_df.index = pd.to_datetime(pos_df.index)
        if not isinstance(mktcap_df.index, pd.DatetimeIndex):
            mktcap_df.index = pd.to_datetime(mktcap_df.index)

        # 以 pos_df 为主，对齐市值表
        mktcap_df = mktcap_df.reindex(index=pos_df.index, columns=pos_df.columns)

        # --- 2. 过滤 startdate 之后 ---
        start_ts = pd.to_datetime(startdate)
        pos_sub = pos_df[pos_df.index >= start_ts].sort_index()
        mktcap_sub = mktcap_df[mktcap_df.index >= start_ts].sort_index()

        # --- 3. 只保留指定月份 & 每月 15 号（含）之后的行 ---
        mask_month = pos_sub.index.month.isin(month_list)
        mask_day = pos_sub.index.day >= 15
        pos_candidate = pos_sub[mask_month & mask_day]
        mktcap_candidate = mktcap_sub[mask_month & mask_day]

        if pos_candidate.empty:
            return pd.DataFrame(columns=["调整日期", "证券代码", "持仓权重", "是否融资融券"])

        # --- 4. 对每个 year-month 只取“第一行”作为调仓日 ---
        periods = pos_candidate.index.to_period("M")
        first_mask = ~periods.duplicated()
        adjust_dates = pos_candidate.index[first_mask]

        records = []
        for dt in adjust_dates:
            pos_row = pos_sub.loc[dt]        # 0/1 持仓
            cap_row = mktcap_sub.loc[dt]     # 对应市值

            # 只保留持仓为 1 的股票
            mask = (pos_row == 1)
            if mask.sum() == 0:
                continue

            # 取出这些股票的市值（保持索引是代码）
            selected_caps = cap_row[mask]

            # 统一转 float，便于后续判断
            selected_caps = selected_caps.astype(float)

            # 标记“好市值”和“坏市值”
            # 好市值：非 NaN 且 > 1e-8
            good_mask = (~selected_caps.isna()) & (selected_caps > 1e-8)
            bad_mask = ~good_mask

            n = len(selected_caps)
            n_bad = int(bad_mask.sum())
            n_good = n - n_bad

            # 如果所有市值都不好，就全部等权
            if n_good == 0:
                weights = pd.Series(1.0 / n, index=selected_caps.index)
            else:
                # 坏市值股票：先固定分到 1/n
                base_w = 1.0 / n
                weights = pd.Series(0.0, index=selected_caps.index)
                weights[bad_mask] = base_w

                # 剩余权重池
                remaining_w = 1.0 - n_bad * base_w
                # 理论上 remaining_w >= 0，但保险再裁一下
                remaining_w = max(remaining_w, 0.0)

                # 好市值股票，根据市值比例分配剩余权重
                caps_good = selected_caps[good_mask]
                sum_good = caps_good.sum()

                if sum_good <= 0 or remaining_w <= 0:
                    # 极端情形：好市值和坏市值逻辑崩了，就退化为等权
                    weights[:] = 1.0 / n
                else:
                    weights[good_mask] = caps_good / sum_good * remaining_w

            # 生成记录
            for code, w in weights.items():
                records.append({
                    "调整日期": dt,        # 如果想用字符串，可以改成 dt.strftime('%Y%m%d')
                    "证券代码": code,
                    "持仓权重": float(w),
                    "是否融资融券": ""     # 先留空
                })

        result_df = pd.DataFrame(
            records,
            columns=["调整日期", "证券代码", "持仓权重", "是否融资融券"]
        )
        return result_df
    
    def weight_cal(self,only_generate_method_number):
        
        
        num = only_generate_method_number
        df = pd.read_pickle(os.path.join(config.output_folder_path,'Value_Index_'+ str(num) + '.pkl'))
        df_size = pd.read_pickle(config.data_path('S_VAL_MV','processed'))
        
        if self.weight == 'size':
            df_out = self.gen_rebalance_df_by_weight_df(df,df_size,startdate=self.start_date)
            df_out_q = self.gen_rebalance_df_by_weight_df(df,df_size,startdate = self.start_date,month_list=self.change_month_list)
            weight_name = 'SizeWeight'
        else:
            df_out = self.gen_rebalance_df(df,startdate=self.start_date)
            df_out_q = self.gen_rebalance_df(df,startdate = self.start_date,month_list=self.change_month_list)
            weight_name = 'EqWeight'
        
        df_out['调整日期'] = df_out['调整日期'].apply(TimestampUtils.date_everything_2_date)
        df_out_q['调整日期'] = df_out_q['调整日期'].apply(TimestampUtils.date_everything_2_date)
        
        # df_out.to_pickle(os.path.join(config.output_folder_path,'Value_Index_1.pkl'))
        DataOs.save_sheet_2_excel(os.path.join(config.output_folder_path,'POS_'+ str(num) + '_' + weight_name + '_monthly.xlsx'),df_out,write_index=False)
        
        # df_out.to_pickle(os.path.join(config.output_folder_path,'Value_Index_1.pkl'))
        Q_month ='_'
        for i in self.change_month_list:
            Q_month += str(i)
            Q_month += '-'
        Q_month = Q_month[:-1]
        DataOs.save_sheet_2_excel(os.path.join(config.output_folder_path,'POS_'+ str(num) + '_' + weight_name + '_Quarter' + Q_month + '.xlsx'),df_out_q,write_index=False)
        
    def main(self):
        
        ## 生成仓位
        for num in self.only_generate_method_number:
            self.weight_cal(num)
            print('方法' + str(num) +'仓位生成完毕!')
            
        
    

        
        print('Index2Weight 完成')

def main():
    
    # ## 0 参数
    # # start_date = 20160101
    start_date = 20160101
    end_date = 20251120
    
    method_list = [1,3]
    if_save_excel = True
    
    # ## 1 进行数据采集
    # dld_v = DownloadValue(start_date,end_date)
    # dld_v.main()


    # ## 2 进行数据处理
    # DataProcess(if_save_excel = if_save_excel).main()
    
    # # 3 数据筛选
    # blacklist = ['BJ']
    # IndexProcess(blacklist=blacklist,only_generate_method_number=method_list).main()
    
    # ## 4 生成pms模板
    # weight = 'size' #依据市值分权
    # weight = 'equal'
    # change_month_list = [2, 5, 8, 11] # 季度调仓月份
    # start_date='20190115' # 开始生成仓位日期
    # Index2Weight(only_generate_method_number=method_list,start_date=start_date,weight = weight,change_month_list = change_month_list).main()
    
    
    ## Fin
    print()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(now_str)
    print('全部完成!')


def test():
    
    
    
    
    
    
    
    # start_date = 20220101
    # end_date = 20251120
    
    
    
    # method_list = [3]
    
    
    # ## 1 进行数据采集
    # dld_v = DownloadValue(start_date,end_date)
    # dld_v.main()
    
    
    if_save_excel = True
    ## 2 进行数据处理
    DataProcess(if_save_excel = if_save_excel).main()
    
    
    
    
    
    
    
    
    print('test finished')
    pass
 

if __name__ == "__main__":
    
    do_do = 'test'
    
    tic = datetime.now()
    
    
    ignore_warning()
    if do_do == 'main':
        main()
    elif do_do == 'test':
        test()
        
    else:
        print('输入main或test')
        
        
    toc = datetime.now()
    spend_time = (toc - tic).total_seconds()   # 秒数
    print('总耗时%.2f秒'%spend_time)