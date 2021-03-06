import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from IPython.display import clear_output

import gym
from gym import spaces

from bg_trade.utils import validate_data
from bg_trade.portfolio import Portfolio



class TradingEnvironment(gym.Env):
    
    metadata = {'render.modes': ['human']}
    desc = 'Base'
    
    def __init__(self, stock_data, balance_init=1e6, fee=2e-2):
        
        super(TradingEnvironment, self).__init__()

        self.fee = fee
        self.balance_init = balance_init
        
        self.agent_portfolio = Portfolio(
            list(stock_data.keys()), 
            self.balance_init, 
            self.fee,
        )
        
        self.long_portfolio = Portfolio(
            list(stock_data.keys()), 
            self.balance_init, 
            self.fee,
        )
    
        self.stocks = stock_data.copy()
        self.validate_data(self.stocks)
        
        self.positions = ( *[t for t in self.stocks.keys()], '_out', )
        self.n_obs = len(self.stocks[self.positions[0]])
        self.n_stocks = len(self.stocks)
        
        self.action_space = spaces.Box(
            low=np.append(np.full(self.n_stocks, -1), 0),
            high=1.,
            shape=(self.n_stocks+1, ),
            dtype=np.float64,
        )

        self.observation_space = spaces.Box(
            low=-np.inf, 
            high=np.inf, 
            shape=(self.n_stocks, 7),
        )
        
    def _next_observation(self):
        
        full_observation = []
        
        for ticker, df in self.stocks.items():
            
            obs = df.loc[
                self.current_step,
                ['close', 'volume', 'ma_30', 'ma_5', 'volatil', 'diff', 'diff_ma_5'],
            ]
                        
            full_observation.append(obs)
            
        return np.array(full_observation).reshape(self.observation_space.shape).astype(np.float64)
    
    def _take_action(self, action):
                
        actions_long = {ticker: 1 for ticker in self.stocks.keys()}
        prices = {ticker: df.loc[self.current_step, 'close'] for ticker, df in self.stocks.items()}
        
        self.agent_portfolio.make_trade(action, prices)
        self.long_portfolio.make_trade(actions_long, prices)
        
        self.net_worth.append(self.agent_portfolio.net_worth)
        self.net_worth_long.append(self.long_portfolio.net_worth)
        
        self.balance = self.agent_portfolio.balance
        self.shares_held = sum(self.agent_portfolio.positions_full.values())
            
    def step(self, action):
        
        if not isinstance(action, dict):
            action = self.format_action(self.positions, action)
        
        self._take_action(action)
        self.current_step += 1
        
        obs = self._next_observation()
        
        reward = (self.agent_portfolio.profits[-1] - self.long_portfolio.profits[-1]) / self.balance_init

        done = (round(self.balance, 9) < 0) or (self.current_step >= self.n_obs-1)
        
        info = {}
        
        return obs, reward, done, info      
    
    def reset(self):
        
        self.current_step = 1

        self.agent_portfolio.reset()
        self.long_portfolio.reset()
                
        self.balance = self.balance_init
        self.net_worth = [self.balance]
        self.net_worth_long = [self.balance]
        self.shares_held = 0
        
        return self._next_observation()
        
    def render(self, mode='human', figsize=(16,10), indicator='close'):
        
        clear_output(wait=True)
        
        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(2,2)

        ax1 = fig.add_subplot(gs[0,:])
        ax2 = fig.add_subplot(gs[1,0])
        ax3 = fig.add_subplot(gs[1,1])

        for ticker, df in self.stocks.items():
            
            date_range = df.loc[1:self.current_step, 'date']
            stock_dta = df.loc[1:self.current_step, indicator]
            
            ax1.plot(
                date_range, 
                stock_dta/df[indicator].std(), 
                label=f'{ticker.upper()} ({indicator})',
            )
                    
        ax2.bar(
            [k if '_' in k else k.upper() for k in self.agent_portfolio.positions_norm.keys()],
            [v for v in self.agent_portfolio.positions_norm.values()],
        )
                    
        ax3.plot(df.loc[1:self.current_step, 'date'], self.net_worth, label='Agent Strategy')
        ax3.plot(df.loc[1:self.current_step, 'date'], self.net_worth_long, label='Long Strategy')
        
        ax1.set_title('Indicator History')
        ax1.legend(loc='upper left')
        
        ax2.set_title('Exposures')
        
        ax3.set_title('Net Worth')
        ax3.legend(loc='upper left')
        
        plt.show()

    @staticmethod
    def format_action(positions, quantities):
        
        assert hasattr(positions, '__iter__')
        assert hasattr(quantities, '__iter__')
        assert len(positions) == len(quantities)
        
        pq = zip(positions, quantities)
        
        return dict(pq)   
    
    @staticmethod
    def validate_data(data):
        
        assert isinstance(data, dict)
        
        validate_data(data)
    

    
class TradingEnvSimple(TradingEnvironment):
    
    desc = """Base trading environment with simple observation space and reward function"""

    

class TradingEnvNorm(TradingEnvironment):
    
    desc = """Trading environment with expanded observation space, normalized outputs, and advanced reward function"""
    
    def __init__(self, stock_data, balance_init=1e6, fee=1e-3, norms=None):
        
        super(TradingEnvNorm, self).__init__(stock_data, balance_init, fee)

        self.normalizers = norms

        self.observation_space = spaces.Box(
            low=-np.inf, 
            high=np.inf, 
            shape=(self.n_stocks+1, 9),
        )
        
    def _next_observation(self):
        
        full_observation = []
        
        for ticker, df in self.stocks.items():
            
            obs = df.loc[
                self.current_step,
                ['close', 'volume', 'ma_30', 'ma_5', 'volatil', 'diff', 'diff_ma_5'],
            ]
                        
            # Normalize observation
            obs = list( (obs.values-self.normalizers[ticker]['shift']) / self.normalizers[ticker]['scale'] )
                                                         
            obs.append(self.agent_portfolio.positions_norm[ticker])
            obs.append(self._price_per_share(
                self.net_worth[-1], 
                self.balance, 
                self.agent_portfolio.positions_full[ticker], 
                self.agent_portfolio.positions_norm[ticker],
            ))
            
            full_observation.append(obs)
            
        meta = np.zeros(self.observation_space.shape[1])    
        
        meta[0] = (self.net_worth[-1] - self.balance_init) / self.balance_init # Profit
        meta[1] = (self.net_worth[-1] - self.balance) / self.balance_init # Invested
        meta[2] = self.net_worth[-1] / self.balance_init # Net worth
        meta[3] = self.balance / self.balance_init # Liquid
        meta[4] = self._price_per_share(self.net_worth[-1], self.balance, self.shares_held, 1.0) # Price per shares
        
        full_observation.append(meta)
            
        return np.array(full_observation).reshape(self.observation_space.shape) 

    def _reward_fn(self):
        
        penalty = (1 / np.sqrt(self.n_stocks+1)) + 1

        return (
            + ( (self.agent_portfolio.profits[-1] - self.long_portfolio.profits[-1]) / abs(self.long_portfolio.profits[-1]) )
            + ( (self.agent_portfolio.net_worth - self.long_portfolio.net_worth) / abs(self.long_portfolio.net_worth) )
            + sum( -penalty for i in self.agent_portfolio.positions_full.values() if i < 1 )
        )
    
    def step(self, action):
        
        if not isinstance(action, dict):
            action = self.format_action(self.positions, action)
        
        self._take_action(action)
        self.current_step += 1
        
        # Observation
        obs = self._next_observation()
        
        # Reward        
        reward = self._reward_fn()

        # Done
        done = (round(self.balance, 9) < 0) or (self.current_step >= self.n_obs-1)
        
        # Information
        info = {}
        
        return obs, reward, done, info    
        
    def render(self, mode='human', figsize=(16,10), indicator='close'):
        
        clear_output(wait=True)
                
        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(2,2)

        ax1 = fig.add_subplot(gs[0,:])
        ax2 = fig.add_subplot(gs[1,0])
        ax3 = fig.add_subplot(gs[1,1])

        for ticker, df in self.stocks.items():
                        
            date_range = df.loc[1:self.current_step, 'date']
            stock_dta = (
                (df.drop('date', axis=1) - self.normalizers[ticker]['shift'])
                / self.normalizers[ticker]['scale']
                ).loc[1:self.current_step, indicator]
                        
            ax1.plot(
                date_range, 
                stock_dta, 
                label=f'{ticker.upper()} ({indicator})',
            )
                    
        ax2.bar(
            [k if '_' in k else k.upper() for k in self.agent_portfolio.positions_norm.keys()],
            [v for v in self.agent_portfolio.positions_norm.values()],
        )
                    
        ax3.plot(df.loc[1:self.current_step, 'date'], self.net_worth, label='Agent Strategy')
        ax3.plot(df.loc[1:self.current_step, 'date'], self.net_worth_long, label='Long Strategy')
        
        ax1.set_title('Indicator History')
        ax1.legend(loc='upper left')
        
        ax2.set_title('Exposures')
        
        ax3.set_title('Net Worth')
        ax3.legend(loc='upper left')
        
        plt.show()
    
    @property
    def normalizers(self):
        
        return self._normalizers
    
    @normalizers.setter
    def normalizers(self, norms):
        
        if norms is None:
            
            self._normalizers = {}

            for ticker, df in self.stocks.items():
                self._normalizers[ticker] = {
                    'scale': df.drop('date', axis=1).std().values,
                    'shift': df.drop('date', axis=1).loc[0].values,
                }
                
        elif isinstance(norms, dict):
            
            assert set(norms.keys()) == set(self.stocks.keys())
            assert all(
                set(item.keys()) == {'scale', 'shift'}
                for item in norms.values()
            )
            
            self._normalizers = norms
        
        else:
            raise ValueError
    
    @staticmethod
    def _price_per_share(net_worth, balance, shares, portion):
        
        if shares >= 1:
            pps = (
                (net_worth - balance) * portion
                ) / shares
            pps = np.log(pps) if pps != 0 else 0
            
        else:
            pps = 0
            
        return pps
    
    
    
class TradingEnvMaxScale(TradingEnvironment):
        
    desc = """Trading environment with expanded observation space, max-scaled outputs, and advanced reward function"""

    def __init__(self, stock_data, balance_init=1e6, fee=1e-3):
        
        super(TradingEnvMaxScale, self).__init__(stock_data, balance_init, fee)

        self.observation_space = spaces.Box(
            low=-np.inf, 
            high=np.inf, 
            shape=(self.n_stocks+1, 9),
        )
        
    def _next_observation(self):
        
        full_observation = []
        
        for ticker, df in self.stocks.items():
            
            _obs = df.loc[
                self.current_step,
                ['close', 'volume', 'ma_30', 'ma_5', 'volatil', 'diff', 'diff_ma_5'],
            ]
                     
            # Scale observations
            obs = list(_obs.values/self.scalers[ticker])
            
            obs.append(self.agent_portfolio.positions_norm[ticker])
            obs.append(self._price_per_share(
                self.net_worth[-1], 
                self.balance, 
                self.agent_portfolio.positions_full[ticker], 
                self.agent_portfolio.positions_norm[ticker],
            ))
            
            full_observation.append(obs)
            self._update_scalers(self.scalers[ticker], _obs.values)
            
        meta =  np.zeros(self.observation_space.shape[1])
    
        meta[0] = (self.net_worth[-1] - self.balance_init) / self.balance_init # Profit
        meta[1] = (self.net_worth[-1] - self.balance) / self.balance_init # Invested
        meta[2] = self.net_worth[-1] / self.balance_init # Net worth
        meta[3] = self.balance / self.balance_init # Liquid
        meta[4] = self._price_per_share(self.net_worth[-1], self.balance, self.shares_held, 1.0) # Price per shares
        
        full_observation.append(meta)
            
        return np.array(full_observation).reshape(self.observation_space.shape) 
            
    def _reward_fn(self):
        
        penalty = (1 / np.sqrt(self.n_stocks+1)) + 1

        return (
            + ( (self.agent_portfolio.profits[-1] - self.long_portfolio.profits[-1]) / abs(self.long_portfolio.profits[-1]) )
            + ( (self.agent_portfolio.net_worth - self.long_portfolio.net_worth) / abs(self.long_portfolio.net_worth) )
            + sum( -penalty for i in self.agent_portfolio.positions_full.values() if i < 1 )
        )
    
    def step(self, action):
        
        if not isinstance(action, dict):
            action = self.format_action(self.positions, action)
        
        self._take_action(action)
        self.current_step += 1
        
        # Observation
        obs = self._next_observation()
        
        # Reward        
        reward = self._reward_fn()

        # Done
        done = (round(self.balance, 9) < 0) or (self.current_step >= self.n_obs-1)
        
        # Information
        info = {}
        
        return obs, reward, done, info   
    
    def reset(self):
        
        self.current_step = 1

        self.agent_portfolio.reset()
        self.long_portfolio.reset()
                
        self.balance = self.balance_init
        self.net_worth = [self.balance]
        self.net_worth_long = [self.balance]
        self.shares_held = 0
        
        self.scalers = self._configure_scalers_init(
            self.stocks,
            self.current_step-1,
        )

        return self._next_observation()
        
    @staticmethod
    def _update_scalers(scalers, obs):

        scalers[:] = [
            max(scalers[i], obs[i]) for i in np.arange(len(scalers))
        ]
    
    @staticmethod
    def _configure_scalers_init(stocks, start=0):
        
        i = 0 + start
        scalers_full = {}
        
        for ticker, df in stocks.items():
            # Scalers are the first observation values
            scalers = df.drop('date', axis=1).values[i]
            
            # If there are zeros in the scalers, use next observation
            while 0. in scalers:
                i += 1
                scalers[scalers==0] = df.drop('date', axis=1).values[i][scalers==0]
            
            scalers_full[ticker] = scalers
            
        return scalers_full

    @staticmethod
    def _price_per_share(net_worth, balance, shares, portion):
        
        if shares >= 1:
            pps = (
                (net_worth - balance) * portion
                ) / shares
            pps = np.log(pps) if pps != 0 else 0
            
        else:
            pps = 0
            
        return pps
    

        